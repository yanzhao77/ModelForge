"""Training service: persisted fine-tuning jobs running in isolated subprocesses."""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from core.config import settings
from models.records import Dataset, TrainTask
from services.model_manager import ModelManager


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


class TrainingService:
    """Manages fine-tuning tasks: launch, poll, stop, stream logs, register output."""

    POLL_INTERVAL = 2.0

    def __init__(self):
        self._procs: Dict[str, subprocess.Popen] = {}

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
        if not config.get("base_model"):
            raise ValueError("必须指定基础模型")

        if len(self._procs) >= settings.train_max_workers:
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
        }
        cfg_path = os.path.join(output_dir, "config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)

        row = TrainTask(
            task_id=task_id,
            user_id=user_id,
            dataset_id=dataset_id,
            base_model=config["base_model"],
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

    # ---- query / stop / register ----

    def get(self, db: DBSession, task_id: str, user_id: int) -> Optional[TrainTask]:
        return db.query(TrainTask).filter_by(task_id=task_id, user_id=user_id).first()

    def list(self, db: DBSession, user_id: int) -> List[TrainTask]:
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
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        if row.status in ("pending", "starting", "running"):
            row.status = "stopped"
            row.error = "stopped by user"
            db.commit()
        return True

    def register_model(self, db: DBSession, task_id: str, user_id: int) -> dict:
        row = self.get(db, task_id, user_id)
        if not row:
            raise ValueError("任务不存在")
        if row.status != "done":
            raise ValueError(f"任务未完成（当前状态: {row.status}）")
        name = f"{row.base_model}-{row.method}-ft"
        model_format = "safetensors" if row.method == "full" else "peft-adapter"
        mm = ModelManager(db)
        model = mm.install(
            name, "training", row.output_dir, "", user_id, model_format=model_format
        )
        return model.to_dict()

    @staticmethod
    def templates() -> Dict:
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


def get_log_tail(log_path: str, max_lines: int = 200) -> List[str]:
    if not log_path or not os.path.exists(log_path):
        return []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [l.rstrip("\n") for l in lines[-max_lines:]]