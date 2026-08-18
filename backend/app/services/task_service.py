"""Persistent task center service and normalized task lifecycle."""
from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.records import TaskEvent, TaskOutbox, TaskRecord

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "PARTIAL"}
NON_TERMINAL = {"QUEUED", "SCHEDULED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED", "RETRYING"}
TRANSITIONS = {
    "QUEUED": {"SCHEDULED", "RUNNING", "CANCELLED", "FAILED", "SUCCEEDED", "PARTIAL"},
    "SCHEDULED": {"QUEUED", "CANCELLED", "FAILED"},
    "RUNNING": {"WAITING_INPUT", "CANCEL_REQUESTED", "SUCCEEDED", "FAILED", "PARTIAL"},
    "WAITING_INPUT": {"RUNNING", "CANCEL_REQUESTED", "CANCELLED", "FAILED"},
    "CANCEL_REQUESTED": {"CANCELLED", "FAILED", "PARTIAL"},
    "RETRYING": {"QUEUED", "FAILED"},
    "FAILED": {"RETRYING"},
    "PARTIAL": {"RETRYING"},
}


TRAINING_STATUS = {
    "pending": "QUEUED", "starting": "QUEUED", "running": "RUNNING",
    "done": "SUCCEEDED", "error": "FAILED", "stopped": "CANCELLED",
}
AGENT_STATUS = {
    "PENDING": "QUEUED", "RUNNING": "RUNNING", "WAITING_TOOL": "WAITING_INPUT",
    "WAITING_HUMAN": "WAITING_INPUT", "COMPLETED": "SUCCEEDED", "SUCCEEDED": "SUCCEEDED",
    "FAILED": "FAILED", "CANCELLED": "CANCELLED", "TIMEOUT": "FAILED",
}


def project_legacy_tasks(db: Session, user_id: int) -> list[TaskRecord]:
    """Project existing training and Agent Run records into task center snapshots.

    The legacy domain rows remain their detailed source of truth. This adapter is
    intentionally idempotent and can run on every task-list refresh until the
    owning services publish transitions directly in a later migration phase.
    """
    from models.records import AgentRun, TrainTask

    service = TaskService()
    projected: list[TaskRecord] = []
    for row in db.query(TrainTask).filter_by(user_id=user_id).all():
        status = TRAINING_STATUS.get((row.status or "pending").lower(), "RUNNING")
        projected.append(service.project(
            db,
            user_id=user_id,
            task_type="training_run",
            source="training",
            source_task_id=row.task_id,
            title=f"训练：{row.base_model}",
            status=status,
            summary=row.error or (f"Epoch {row.current_epoch or 0}/{row.total_epochs or 0}"),
            progress_percent=int(row.progress or 0) if row.progress is not None else None,
            cancelable=status not in TERMINAL,
            retryable=status in {"FAILED", "CANCELLED"},
            metadata={"base_model": row.base_model, "method": row.method, "output_dir": row.output_dir},
        ))
    for row in db.query(AgentRun).filter_by(user_id=user_id).all():
        status = AGENT_STATUS.get(row.status or "PENDING", "RUNNING")
        projected.append(service.project(
            db,
            user_id=user_id,
            task_type="agent_run",
            source="agent_runtime",
            source_task_id=row.run_id,
            title=f"Agent：{row.agent_id}",
            status=status,
            summary=row.error or (row.input or "等待执行"),
            cancelable=status not in TERMINAL,
            retryable=status in {"FAILED", "CANCELLED"},
            metadata={"agent_id": row.agent_id, "session_id": row.session_id, "model": row.model},
        ))
    return projected


def _dump(value: Any) -> Optional[str]:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value is not None else None


class TaskConflict(ValueError):
    pass


class TaskService:
    """Single write boundary for persistent product task state and events."""

    def _append_event(self, db: Session, task: TaskRecord, event_type: str, payload: dict) -> TaskEvent:
        event = TaskEvent(
            task_id=task.task_id,
            user_id=task.user_id,
            event_type=event_type,
            version=task.version,
            payload=_dump(payload) or "{}",
        )
        db.add(event)
        db.flush()
        db.add(TaskOutbox(
            event_id=event.id,
            user_id=task.user_id,
            event_type=event_type,
            payload=event.payload,
        ))
        return event

    def create(
        self,
        db: Session,
        *,
        user_id: int,
        task_type: str,
        source: str,
        title: str,
        summary: str | None = None,
        metadata: dict | None = None,
        cancelable: bool = False,
        retryable: bool = False,
        priority: str = "normal",
        source_task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> TaskRecord:
        if idempotency_key:
            existing = db.query(TaskRecord).filter_by(user_id=user_id, idempotency_key=idempotency_key).first()
            if existing:
                return existing
        task = TaskRecord(
            task_id=uuid.uuid4().hex,
            user_id=user_id,
            task_type=task_type,
            source=source,
            source_task_id=source_task_id,
            title=title,
            summary=summary,
            status="QUEUED",
            metadata=_dump(metadata or {}),
            cancelable=cancelable,
            retryable=retryable,
            priority=priority if priority in {"low", "normal", "high"} else "normal",
            idempotency_key=idempotency_key,
        )
        db.add(task)
        db.flush()
        self._append_event(db, task, "task.created", {"task": task.to_dict()})
        db.commit()
        db.refresh(task)
        return task

    def transition(
        self,
        db: Session,
        task: TaskRecord,
        status: str,
        *,
        summary: str | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        progress_unit: str | None = None,
        progress_percent: int | None = None,
        result: dict | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        error_detail: dict | None = None,
        required_action: dict | None = None,
        expected_version: int | None = None,
    ) -> TaskRecord:
        if expected_version is not None and task.version != expected_version:
            raise TaskConflict("TASK_VERSION_CONFLICT")
        if status != task.status and status not in TRANSITIONS.get(task.status, set()):
            raise TaskConflict(f"Illegal transition: {task.status} -> {status}")
        now = datetime.utcnow()
        if status != task.status:
            task.status = status
            task.version += 1
        if status == "RUNNING" and task.started_at is None:
            task.started_at = now
        if status in TERMINAL:
            task.completed_at = now
        if summary is not None:
            task.summary = summary
        if progress_current is not None:
            task.progress_current = progress_current
        if progress_total is not None:
            task.progress_total = progress_total
        if progress_unit is not None:
            task.progress_unit = progress_unit
        if progress_percent is not None:
            task.progress_percent = max(0, min(100, progress_percent))
        if result is not None:
            task.result = _dump(result)
        if error_code is not None:
            task.error_code = error_code
        if error_message is not None:
            task.error_message = error_message
        if error_detail is not None:
            task.error_detail = _dump(error_detail)
        if required_action is not None:
            task.required_action = _dump(required_action)
        task.updated_at = now
        self._append_event(db, task, "task.updated", {"task": task.to_dict()})
        db.commit()
        db.refresh(task)
        return task

    def project(
        self,
        db: Session,
        *,
        user_id: int,
        task_type: str,
        source: str,
        source_task_id: str,
        title: str,
        status: str,
        summary: str | None = None,
        progress_percent: int | None = None,
        cancelable: bool = False,
        retryable: bool = False,
        metadata: dict | None = None,
    ) -> TaskRecord:
        task = db.query(TaskRecord).filter_by(source=source, source_task_id=source_task_id).first()
        if task is None:
            task = self.create(
                db, user_id=user_id, task_type=task_type, source=source, source_task_id=source_task_id,
                title=title, summary=summary, cancelable=cancelable, retryable=retryable, metadata=metadata,
            )
        if task.user_id != user_id:
            raise TaskConflict("TASK_OWNERSHIP_CONFLICT")
        if task.status == "QUEUED" and status == "QUEUED":
            return task
        if task.status == "CANCEL_REQUESTED" and status == "RUNNING":
            return task
        if task.status != status or progress_percent is not None or summary is not None:
            if status == "QUEUED" and task.status != "QUEUED":
                status = task.status
            self.transition(
                db, task, status, summary=summary, progress_percent=progress_percent,
            )
        return task

    def list(self, db: Session, user_id: int, *, status: str | None = None, task_type: str | None = None, limit: int = 100, offset: int = 0):
        query = db.query(TaskRecord).filter_by(user_id=user_id)
        if status:
            statuses = [value.strip() for value in status.split(",") if value.strip()]
            query = query.filter(TaskRecord.status.in_(statuses))
        if task_type:
            query = query.filter_by(task_type=task_type)
        return query.order_by(TaskRecord.updated_at.desc(), TaskRecord.id.desc()).offset(max(0, offset)).limit(max(1, min(200, limit))).all()

    def get(self, db: Session, task_id: str, user_id: int) -> TaskRecord | None:
        return db.query(TaskRecord).filter_by(task_id=task_id, user_id=user_id).first()

    def summary(self, db: Session, user_id: int) -> dict:
        rows = db.query(TaskRecord.status).filter_by(user_id=user_id).all()
        counts = Counter(row[0] for row in rows)
        active = sum(counts.get(status, 0) for status in NON_TERMINAL)
        needs_attention = counts.get("FAILED", 0) + counts.get("PARTIAL", 0) + counts.get("WAITING_INPUT", 0)
        return {"total": sum(counts.values()), "active": active, "needs_attention": needs_attention, "by_status": dict(counts)}

    def events(self, db: Session, task: TaskRecord, limit: int = 200) -> list[TaskEvent]:
        return db.query(TaskEvent).filter_by(task_id=task.task_id, user_id=task.user_id).order_by(TaskEvent.id.desc()).limit(max(1, min(500, limit))).all()[::-1]

    def events_after(self, db: Session, user_id: int, after_id: int, limit: int = 200) -> list[TaskEvent]:
        """Return immutable task events in global cursor order for SSE recovery."""
        return (
            db.query(TaskEvent)
            .filter(TaskEvent.user_id == user_id, TaskEvent.id > max(0, after_id))
            .order_by(TaskEvent.id.asc())
            .limit(max(1, min(500, limit)))
            .all()
        )

    def request_cancel(self, db: Session, task: TaskRecord) -> TaskRecord:
        if not task.cancelable:
            raise TaskConflict("TASK_NOT_CANCELABLE")
        if task.status in TERMINAL:
            raise TaskConflict("TASK_ALREADY_TERMINAL")
        return self.transition(db, task, "CANCEL_REQUESTED", summary="已请求取消，等待执行器确认")
