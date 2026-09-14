"""Training service: persisted fine-tuning jobs running in isolated subprocesses."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from core.config import settings
from models.records import Dataset, TrainTask, User
from services.model_capabilities import ModelCapability
from services.model_manager import ModelManager
from services.model_registry import ModelRegistry, ModelRegistryError
from services.resource_lease import training_lease
from sqlalchemy.orm import Session as DBSession


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _coerce_optional_int(value) -> int | None:
    """Parse an optional numeric identifier, tolerating strings from JSON."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_model_name(value: str | None) -> str:
    """Derive a filesystem- and display-safe name from a base model label.

    Legacy tasks stored a repo id or an absolute path in ``base_model``; using it
    verbatim produced record names containing ``/`` or ``\\``.
    """
    text = str(value or "model").strip().replace("\\", "/")
    leaf = text.rstrip("/").split("/")[-1] or "model"
    cleaned = "".join(char if (char.isalnum() or char in {"-", "_", "."}) else "-" for char in leaf)
    return cleaned.strip("-") or "model"


def _load_task_config(row: TrainTask) -> dict:
    """Read the persisted training config without failing on legacy rows."""
    try:
        payload = json.loads(row.config or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class TrainingService:
    """Manages fine-tuning tasks: launch, poll, stop, stream logs, register output."""

    POLL_INTERVAL = 2.0
    #: Capability a base model must expose before it can be fine-tuned.
    REQUIRED_BASE_CAPABILITY = ModelCapability.TRAINING.value

    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}

    # ---- launch ----

    def start(self, db: DBSession, user_id: int, config: dict) -> TrainTask:
        if not _torch_available():
            raise RuntimeError(
                "训练需要 AI 依赖（torch/transformers），请先安装 requirements-ai.txt"
            )
        dataset_id = config.get("dataset_id")
        dataset_path = config.get("dataset_path")
        dataset_format = config.get("dataset_format", "json")
        if dataset_id:
            ds = db.query(Dataset).filter_by(id=dataset_id, user_id=user_id).first()
            if ds is None:
                raise ValueError("数据集不存在")
            dataset_path = ds.file_path
            dataset_format = ds.format
        if not dataset_path or not os.path.exists(dataset_path):
            raise ValueError("数据集路径无效")

        # The base model is resolved through the unified registry so the same
        # asset is used by inference and training. A capability check runs here
        # (not only in the UI): an inference-only GGUF file must never be handed
        # to the fine-tuning job even if a client asks for it directly.
        base_model_id = _coerce_optional_int(config.get("base_model_id"))
        base_model_ref = str(config.get("base_model") or "").strip()
        base_model_path: str | None = None
        base_model_name: str | None = None
        base_capabilities: list[str] = []
        if base_model_id is not None:
            registry = ModelRegistry(db)
            try:
                record = registry.require(base_model_id, user_id)
                registry.require_ready(record)
                registry.require_capability(record, self.REQUIRED_BASE_CAPABILITY)
                base_model_path = registry.resolve_path(record)
                base_model_name = record.display_name or record.name
                base_capabilities = registry.capabilities(record)
            except ModelRegistryError as exc:
                raise ValueError(exc.message) from exc
        elif base_model_ref:
            base_model_path = base_model_ref
            base_model_name = base_model_ref
        if not base_model_path:
            raise ValueError("必须指定基础模型")

        self._release_finished_processes(db)

        # Training is exclusive: claim the machine before any process is started
        # so a second account gets a clear "busy" answer instead of a race.
        owner = db.query(User).filter_by(id=user_id).first()
        handle = training_lease.acquire(
            user_id=user_id, username=owner.username if owner else str(user_id)
        )
        if len(self._procs) >= settings.train_max_workers:
            if handle.created:
                handle.release()
            raise RuntimeError(f"已有训练任务在运行（上限 {settings.train_max_workers}），请稍后再试")

        task_id = uuid.uuid4().hex[:12]
        output_dir = os.path.join(settings.train_output_dir, task_id)
        os.makedirs(output_dir, exist_ok=True)
        log_path = os.path.join(output_dir, "train.log")
        state_path = os.path.join(output_dir, "state.json")
        cfg = {
            **config,
            "dataset_path": dataset_path,
            "dataset_format": dataset_format,
            "output_dir": output_dir,
            "hf_endpoint": settings.hf_endpoint,
            # The subprocess consumes a resolvable model path / repo id; the row
            # keeps the human-readable base model label.
            "base_model": base_model_path,
            "base_model_id": base_model_id,
            "base_model_name": base_model_name,
            "base_model_capabilities": base_capabilities,
        }
        cfg_path = os.path.join(output_dir, "config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)

        row = TrainTask(
            task_id=task_id,
            user_id=user_id,
            dataset_id=dataset_id,
            base_model=base_model_name or base_model_ref,
            method=config.get("method", "lora"),
            config=json.dumps(cfg, ensure_ascii=False),
            status="starting",
            total_epochs=int(config.get("epochs", 3)),
            output_dir=output_dir,
            log_path=log_path,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        try:
            proc = self._launch(cfg_path, state_path, log_path)
        except Exception as e:
            row.status = "error"
            row.error = f"启动训练进程失败: {e}"
            db.commit()
            if handle.created:
                handle.release()
            raise RuntimeError(row.error)
        self._procs[task_id] = proc
        row.status = "running"
        db.commit()
        threading.Thread(
            target=self._poll, args=(row.id, task_id, state_path, proc), daemon=True
        ).start()
        return row

    def _launch(self, cfg_path: str, state_path: str, log_path: str) -> subprocess.Popen:
        """Launch the training subprocess (override in tests)."""
        script = os.path.join(os.path.dirname(__file__), "runtimes", "training_jobs.py")
        return subprocess.Popen(
            [sys.executable, script, "--config", cfg_path, "--state", state_path, "--log", log_path],
            cwd=os.getcwd(),
        )

    # ---- poll ----

    def _poll(self, row_id: int, task_id: str, state_path: str, proc: subprocess.Popen):
        from core.database import SessionLocal
        owner_id: int | None = None
        while True:
            time.sleep(self.POLL_INTERVAL)
            state = {}
            if os.path.exists(state_path):
                try:
                    with open(state_path, "r", encoding="utf-8") as f:
                        state = json.load(f)
                except Exception:
                    pass
            db = SessionLocal()
            try:
                row = db.query(TrainTask).filter_by(id=row_id).first()
                if row:
                    owner_id = row.user_id
                    if row.status == "stopped":
                        break
                    if state.get("status") == "done":
                        row.status = "done"
                    elif state.get("status") == "error":
                        row.status = "error"
                        row.error = state.get("error")
                    row.progress = state.get("progress", row.progress)
                    row.current_epoch = state.get("epoch", row.current_epoch)
                    if state.get("loss") is not None:
                        row.loss = state["loss"]
                    if proc.poll() is not None and row.status == "running":
                        row.status = "done" if proc.returncode == 0 else "error"
                        if proc.returncode != 0 and not row.error:
                            row.error = f"训练进程退出码 {proc.returncode}"
                    db.commit()
            except Exception:
                pass
            finally:
                db.close()
            if proc.poll() is not None and not state.get("status") == "running":
                break
            if proc.poll() is not None and os.path.exists(state_path):
                break
        self._procs.pop(task_id, None)
        self._release_lease(owner_id)

    # ---- query / stop / register ----

    def get(self, db: DBSession, task_id: str, user_id: int) -> TrainTask | None:
        return db.query(TrainTask).filter_by(task_id=task_id, user_id=user_id).first()

    def list(self, db: DBSession, user_id: int) -> list[TrainTask]:
        return (
            db.query(TrainTask)
            .filter_by(user_id=user_id)
            .order_by(TrainTask.created_at.desc())
            .all()
        )

    def stop(self, db: DBSession, task_id: str, user_id: int) -> bool:
        row = self.get(db, task_id, user_id)
        if not row:
            return False
        proc = self._procs.get(task_id)
        self._procs.pop(task_id, None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        if row.status in ("pending", "starting", "running"):
            row.status = "stopped"
            row.error = "stopped by user"
            db.commit()
        self._release_lease(user_id)
        return True

    @staticmethod
    def _release_lease(user_id: int | None) -> None:
        """Free the training resource only when this account still owns it."""
        if user_id is None:
            return
        holder = training_lease.holder()
        if holder is not None and holder.user_id == user_id:
            training_lease.release(user_id=user_id)

    def _release_finished_processes(self, db: DBSession) -> None:
        """Drop process handles that exited before the poll thread observed them."""
        finished = [task_id for task_id, proc in list(self._procs.items()) if proc.poll() is not None]
        for task_id in finished:
            self._procs.pop(task_id, None)
            row = db.query(TrainTask).filter_by(task_id=task_id).first()
            self._release_lease(row.user_id if row is not None else None)

    def reconcile_orphaned_tasks(self) -> int:
        """Settle trainings left running by a previous process.

        The poll thread only lives in memory, so a row that is still
        pending/starting/running after a restart can never reach a terminal
        state again; the training page would show a phantom run forever and the
        log stream would never end.
        """
        from core.database import SessionLocal

        interrupted = 0
        with SessionLocal() as session:
            rows = (
                session.query(TrainTask)
                .filter(TrainTask.status.in_(("pending", "starting", "running")))
                .all()
            )
            for row in rows:
                if row.task_id in self._procs:
                    continue
                row.status = "error"
                row.error = "训练进程随服务重启中断，请重新开始训练"
                interrupted += 1
            session.commit()
        return interrupted

    def register_model(self, db: DBSession, task_id: str, user_id: int) -> dict:
        row = self.get(db, task_id, user_id)
        if not row:
            raise ValueError("任务不存在")
        if row.status != "done":
            raise ValueError(f"任务未完成（当前状态: {row.status}）")
        task_config = _load_task_config(row)
        base_model_id = _coerce_optional_int(task_config.get("base_model_id"))
        name = f"{_safe_model_name(row.base_model)}-{row.method}-ft"
        model_format = "safetensors" if row.method == "full" else "peft-adapter"
        mm = ModelManager(db)
        source = Path(row.output_dir).resolve()
        if not source.is_dir():
            raise ValueError("训练产物目录不可用")
        # A training output is not an installable model until it is copied into
        # the configured model root. This keeps ModelRecord.path contained even
        # when a legacy task stored a custom output_dir.
        target = mm.model_path / f"user-{user_id}" / row.task_id
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, symlinks=False)
        # A LoRA adapter is only usable next to its base model, so it is
        # registered as LORA (and flagged as requiring a base) rather than
        # pretending it is a standalone chat model.
        if model_format == "peft-adapter":
            capabilities = [ModelCapability.LORA.value]
        else:
            capabilities = [ModelCapability.CHAT.value, ModelCapability.INFERENCE.value]
        metadata = {
            "training_task_id": row.task_id,
            "method": row.method,
            "dataset_id": row.dataset_id,
            "base_model_id": base_model_id,
            "output_path": str(target),
            "format": model_format,
            "requires_base_model": model_format == "peft-adapter",
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        registry = ModelRegistry(db)
        model = registry.register(
            name=name,
            provider="training",
            path=str(target),
            size="",
            user_id=user_id,
            model_format=model_format,
            capabilities=capabilities,
            metadata=metadata,
            base_model_id=base_model_id,
            parent_model_id=base_model_id,
            commit=False,
        )
        db.commit()
        return model.to_dict()

    @staticmethod
    def templates() -> dict:
        """Default hyperparameter templates for the training form."""
        return {
            "full": {
                "epochs": 3, "learning_rate": 2e-5, "batch_size": 2,
                "output_dir": "./outputs",
            },
            "lora": {
                "epochs": 3, "learning_rate": 2e-5, "batch_size": 2,
                "lora_r": 8, "lora_alpha": 32, "output_dir": "./outputs",
            },
        }


def get_log_tail(log_path: str, max_lines: int = 200) -> list[str]:
    if not log_path or not os.path.exists(log_path):
        return []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line_value.rstrip("\n") for line_value in lines[-max_lines:]]


# Running processes must outlive the request that started them, so the service
# (and its ``_procs`` registry, which enforces the single-training rule and makes
# ``stop`` actually terminate the child) is a process-wide singleton.
training_service = TrainingService()


def get_training_service() -> TrainingService:
    return training_service
