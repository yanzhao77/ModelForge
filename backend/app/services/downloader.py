"""User-scoped, persistent model download task service."""
from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime
from pathlib import Path

from core.config import settings
from core.database import SessionLocal
from models.records import DownloadTaskRecord
from sqlalchemy.orm import Session


class Downloader:
    """Persist download state before dispatching background work.

    The process still performs the actual download locally, but the task record
    is a durable source of truth. A process restart therefore yields an honest
    PENDING/RUNNING status rather than exposing another user's in-memory task.
    """

    def __init__(self):
        self._semaphore = asyncio.Semaphore(2)

    def start(
        self,
        repo_id: str,
        user_id: int,
        filename: str | None = None,
        db: Session | None = None,
    ) -> DownloadTaskRecord:
        task = DownloadTaskRecord(
            id=uuid.uuid4().hex,
            user_id=user_id,
            repo_id=repo_id,
            filename=filename,
            status="PENDING",
            progress=0,
            message="Pending",
        )
        session = db or SessionLocal()
        try:
            session.add(task)
            session.commit()
            session.refresh(task)
        except Exception:
            session.rollback()
            raise
        finally:
            if db is None:
                session.close()
        self._schedule(task.id)
        return task

    def _schedule(self, task_id: str) -> None:
        """Schedule safely from either an ASGI loop or a synchronous worker."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            threading.Thread(
                target=lambda: asyncio.run(self._run(task_id)), daemon=True
            ).start()
        else:
            loop.create_task(self._run(task_id))

    def _set_state(
        self,
        task_id: str,
        *,
        status: str,
        progress: int,
        message: str,
        error_code: str | None = None,
        completed: bool = False,
    ) -> DownloadTaskRecord | None:
        with SessionLocal() as session:
            task = session.get(DownloadTaskRecord, task_id)
            if task is None:
                return None
            task.status = status
            task.progress = progress
            task.message = message[:255]
            task.error_code = error_code
            if completed:
                task.completed_at = datetime.utcnow()
            session.commit()
            session.refresh(task)
            return task

    async def _run(self, task_id: str) -> None:
        async with self._semaphore:
            task = self._set_state(task_id, status="RUNNING", progress=0, message="Download started")
            if task is None:
                return
            try:
                from huggingface_hub import snapshot_download

                if settings.hf_endpoint:
                    import os

                    os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
                target = Path(settings.model_dir) / task.repo_id.replace("/", "_")
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                kwargs = {"repo_id": task.repo_id, "local_dir": str(target), "force_download": False}
                if task.filename:
                    kwargs["allow_patterns"] = [task.filename]
                self._set_state(task_id, status="RUNNING", progress=1, message="Download in progress")
                await asyncio.to_thread(snapshot_download, **kwargs)
                self._set_state(task_id, status="COMPLETED", progress=100, message="Download completed", completed=True)
            except Exception:
                # Upstream failures can contain tokens, URLs, and absolute paths;
                # retain a stable code only and keep diagnostic detail in server logs.
                self._set_state(
                    task_id,
                    status="FAILED",
                    progress=0,
                    message="Download failed",
                    error_code="MODEL_DOWNLOAD_FAILED",
                    completed=True,
                )

    def get(self, task_id: str, user_id: int, db: Session | None = None) -> DownloadTaskRecord | None:
        session = db or SessionLocal()
        try:
            return (
                session.query(DownloadTaskRecord)
                .filter_by(id=task_id, user_id=user_id)
                .first()
            )
        finally:
            if db is None:
                session.close()

    def list(self, user_id: int, db: Session | None = None) -> list[DownloadTaskRecord]:
        session = db or SessionLocal()
        try:
            return (
                session.query(DownloadTaskRecord)
                .filter_by(user_id=user_id)
                .order_by(DownloadTaskRecord.created_at.desc())
                .all()
            )
        finally:
            if db is None:
                session.close()

    def search_hf(self, query: str = "", author: str | None = None, limit: int = 20) -> list:
        """Search HuggingFace for models (GGUF-friendly)."""
        from services.hf_provider import HFProvider

        provider = HFProvider()
        results = provider.list_models(query or "gguf", limit=limit)
        if author:
            results = [item for item in results if author.lower() in str(item.get("author", "")).lower()]
        return results


downloader = Downloader()


def get_downloader() -> Downloader:
    return downloader
