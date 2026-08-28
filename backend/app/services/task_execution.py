"""Retry execution adapters and durable task-center progress synchronization."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.database import SessionLocal
from models.records import AgentEventRecord, AgentRun, TaskRecord, TrainTask
from services.agent_runtime_service import get_agent_runtime
from services.downloader import get_downloader
from services.task_service import (
    AGENT_STATUS,
    TERMINAL,
    TRAINING_STATUS,
    TaskConflict,
    TaskService,
)
from services.training import TrainingService
from sqlalchemy.orm import Session


class RetryExecutionError(ValueError):
    """Raised when a retry task cannot be safely handed to an execution adapter."""


class TaskExecutionService:
    """Bridge retry children to legacy executors without weakening task auditability."""

    def __init__(self, task_service: TaskService | None = None) -> None:
        self.tasks = task_service or TaskService()

    @staticmethod
    def _metadata(task: TaskRecord) -> dict[str, Any]:
        return task._json(task.meta, {})

    @staticmethod
    def _set_metadata(task: TaskRecord, metadata: dict[str, Any]) -> None:
        task.meta = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

    def launch_retry(self, db: Session, task: TaskRecord) -> TaskRecord:
        """Claim a queued retry child and start the matching executor exactly once."""
        if task.parent_task_id is None or task.status != "QUEUED":
            raise RetryExecutionError("仅已排队的重试子任务可以被执行器领取")
        try:
            if task.source == "training":
                return self._launch_training(db, task)
            if task.source == "agent_runtime":
                return self._launch_agent(db, task)
            if task.source in {"model_download", "download"}:
                return self._launch_download(db, task)
            raise RetryExecutionError(f"不支持任务来源 {task.source} 的自动重试")
        except RetryExecutionError:
            raise
        except Exception as exc:  # Normalize implementation failures into the task-center contract.
            raise RetryExecutionError(str(exc)) from exc

    def _launch_training(self, db: Session, task: TaskRecord) -> TaskRecord:
        source = (
            db.query(TrainTask)
            .filter_by(task_id=task.source_task_id, user_id=task.user_id)
            .first()
        )
        if source is None:
            raise RetryExecutionError("未找到原始训练任务，无法恢复训练配置")
        try:
            config = json.loads(source.config or "{}")
        except json.JSONDecodeError as exc:
            raise RetryExecutionError("原始训练配置无法解析") from exc
        if not isinstance(config, dict):
            raise RetryExecutionError("原始训练配置格式无效")

        retry_source = TrainingService().start(db, task.user_id, config)
        metadata = self._metadata(task)
        metadata.update({
            "executor": "training",
            "execution_task_id": retry_source.task_id,
            "log_path": retry_source.log_path,
        })
        task.source_task_id = retry_source.task_id
        self._set_metadata(task, metadata)
        return self.tasks.transition(
            db,
            task,
            "RUNNING",
            summary="训练重试已由执行器领取，正在初始化运行环境。",
            progress_percent=int(retry_source.progress or 0),
        )

    def _launch_agent(self, db: Session, task: TaskRecord) -> TaskRecord:
        source = (
            db.query(AgentRun)
            .filter_by(run_id=task.source_task_id, user_id=task.user_id)
            .first()
        )
        if source is None:
            raise RetryExecutionError("未找到原始 Agent 运行，无法恢复输入")
        runtime = get_agent_runtime()
        if runtime is None:
            raise RetryExecutionError("Agent Runtime 尚未就绪，请稍后重试")
        run = runtime.create_run(
            agent_id=source.agent_id,
            input_text=source.input or "",
            user_id=task.user_id,
            session_id=source.session_id,
            metadata={"retry_of": source.run_id, "task_id": task.task_id},
            execute=True,
        )
        metadata = self._metadata(task)
        metadata.update({"executor": "agent_runtime", "execution_task_id": run.run_id})
        task.source_task_id = run.run_id
        self._set_metadata(task, metadata)
        return self.tasks.transition(
            db,
            task,
            "RUNNING",
            summary="Agent 重试已由执行器领取，正在规划执行步骤。",
        )

    def _launch_download(self, db: Session, task: TaskRecord) -> TaskRecord:
        metadata = self._metadata(task)
        repo_id = str(metadata.get("repo_id") or "").strip()
        filename = metadata.get("filename")
        if not repo_id:
            raise RetryExecutionError("下载重试缺少 repo_id，无法恢复下载请求")
        download = get_downloader().start(repo_id, task.user_id, filename, db=db)
        metadata.update({"executor": "downloader", "execution_task_id": download.task_id})
        task.source_task_id = download.task_id
        self._set_metadata(task, metadata)
        return self.tasks.transition(
            db,
            task,
            "RUNNING",
            summary="模型下载重试已由执行器领取，正在建立下载连接。",
            progress_percent=0,
        )

    def fail_dispatch(self, db: Session, task: TaskRecord, error: Exception) -> TaskRecord:
        """Persist a clear, retryable dispatch failure rather than leaving an orphaned queue item."""
        return self.tasks.transition(
            db,
            task,
            "FAILED",
            summary="重试任务未能被执行器领取。",
            error_code="RETRY_DISPATCH_FAILED",
            error_message=str(error),
            error_detail={"retry_of": task.parent_task_id, "source": task.source},
        )

    def synchronize(self, db: Session, task: TaskRecord) -> bool:
        """Project executor state to a retry child only when a material field changed."""
        if task.parent_task_id is None or task.status in TERMINAL:
            return False
        if task.source == "training":
            return self._sync_training(db, task)
        if task.source == "agent_runtime":
            return self._sync_agent(db, task)
        if task.source in {"model_download", "download"}:
            return self._sync_download(db, task)
        return False

    def _transition_if_changed(self, db: Session, task: TaskRecord, status: str, *, summary: str, progress: int | None = None, error: str | None = None, result: dict | None = None) -> bool:
        changed = (
            task.status != status
            or task.summary != summary
            or (progress is not None and task.progress_percent != progress)
            or (error is not None and task.error_message != error)
        )
        if not changed:
            return False
        self.tasks.transition(
            db,
            task,
            status,
            summary=summary,
            progress_percent=progress,
            error_code="EXECUTOR_FAILED" if status == "FAILED" else None,
            error_message=error,
            result=result,
        )
        return True

    def _sync_training(self, db: Session, task: TaskRecord) -> bool:
        source = db.query(TrainTask).filter_by(task_id=task.source_task_id, user_id=task.user_id).first()
        if source is None:
            return self._transition_if_changed(db, task, "FAILED", summary="训练重试源任务不可用。", error="训练任务记录不存在")
        status = TRAINING_STATUS.get((source.status or "pending").lower(), "RUNNING")
        summary = source.error or f"Epoch {source.current_epoch or 0}/{source.total_epochs or 0}"
        result = {"output_dir": source.output_dir} if status == "SUCCEEDED" else None
        return self._transition_if_changed(
            db,
            task,
            status,
            summary=summary,
            progress=int(source.progress or 0),
            error=source.error if status == "FAILED" else None,
            result=result,
        )

    def _sync_agent(self, db: Session, task: TaskRecord) -> bool:
        source = db.query(AgentRun).filter_by(run_id=task.source_task_id, user_id=task.user_id).first()
        if source is None:
            return self._transition_if_changed(db, task, "FAILED", summary="Agent 重试源任务不可用。", error="Agent 运行记录不存在")
        status = AGENT_STATUS.get(source.status or "PENDING", "RUNNING")
        summary = source.error or source.output or source.input or "Agent 正在执行"
        result = {"output": source.output} if status == "SUCCEEDED" and source.output else None
        return self._transition_if_changed(
            db,
            task,
            status,
            summary=summary,
            error=source.error if status == "FAILED" else None,
            result=result,
        )

    def _sync_download(self, db: Session, task: TaskRecord) -> bool:
        source = get_downloader().get(task.source_task_id, task.user_id, db=db)
        if source is None:
            return self._transition_if_changed(db, task, "FAILED", summary="下载重试源任务不可用。", error="下载任务记录不存在")
        status = {"PENDING": "QUEUED", "RUNNING": "RUNNING", "COMPLETED": "SUCCEEDED", "FAILED": "FAILED"}.get(source.status, "RUNNING")
        result = {"download_task_id": source.id, "repo_id": source.repo_id} if status == "SUCCEEDED" else None
        return self._transition_if_changed(
            db,
            task,
            status,
            summary=source.message or "模型下载正在执行",
            progress=int(source.progress or 0),
            error=source.error_code if status == "FAILED" else None,
            result=result,
        )

    def logs(self, db: Session, task: TaskRecord, limit: int = 200) -> dict[str, Any]:
        """Return a bounded execution-log view for the task detail panel."""
        limit = max(1, min(500, limit))
        if task.source == "training":
            source = db.query(TrainTask).filter_by(task_id=task.source_task_id, user_id=task.user_id).first()
            path = Path(source.log_path) if source and source.log_path else None
            if path and path.exists():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
            else:
                lines = []
            return {"source": "training", "lines": lines}
        if task.source == "agent_runtime":
            events = (
                db.query(AgentEventRecord)
                .filter_by(run_id=task.source_task_id)
                .order_by(AgentEventRecord.sequence.desc())
                .limit(limit)
                .all()
            )
            lines = [f"[{event.event_type}] {json.dumps(event.to_dict().get('payload', {}), ensure_ascii=False)}" for event in reversed(events)]
            return {"source": "agent_runtime", "lines": lines}
        if task.source in {"model_download", "download"}:
            source = get_downloader().get(task.source_task_id, task.user_id, db=db)
            lines = [source.message] if source and source.message else []
            if source and source.error_code:
                lines.append(source.error_code)
            return {"source": "downloader", "lines": lines}
        return {"source": task.source, "lines": []}


class RetryTaskMonitor:
    """Background poller that projects retry executor updates into durable task events."""

    def __init__(self, service: TaskExecutionService | None = None, nudge: Callable[[], None] | None = None, interval: float = 1.0) -> None:
        self.service = service or TaskExecutionService()
        self.nudge = nudge
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="retry-task-monitor", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            db = SessionLocal()
            changed = False
            try:
                tasks = (
                    db.query(TaskRecord)
                    .filter(TaskRecord.parent_task_id.isnot(None))
                    .filter(TaskRecord.status.in_(["QUEUED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED"]))
                    .all()
                )
                for task in tasks:
                    try:
                        changed = self.service.synchronize(db, task) or changed
                    except (TaskConflict, ValueError):
                        db.rollback()
            finally:
                db.close()
            if changed and self.nudge:
                self.nudge()
                self.nudge()
