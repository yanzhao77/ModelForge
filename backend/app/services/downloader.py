"""User-scoped, persistent model download task service."""
from __future__ import annotations

import asyncio
import fnmatch
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import settings
from core.database import SessionLocal
from models.records import DownloadTaskRecord, TaskRecord
from sqlalchemy.orm import Session


class DownloadCancelled(Exception):
    """Raised internally when a task-center cancel reaches the downloader."""


@dataclass(frozen=True)
class DownloadFile:
    path: str
    size: int | None
    url: str


class Downloader:
    """Persist download state before dispatching background work.

    The process still performs the actual download locally, but the task record
    is a durable source of truth. A process restart therefore yields an honest
    PENDING/RUNNING status rather than exposing another user's in-memory task.
    """

    def __init__(self, *, max_downloads: int = 2, workers: int = 4):
        self._semaphore = threading.BoundedSemaphore(max_downloads)
        self._workers = max(1, workers)
        self._active: set[str] = set()
        self._active_lock = threading.Lock()

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
        with self._active_lock:
            if task_id in self._active:
                return
            self._active.add(task_id)
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
            try:
                self._project_task(task)
            except Exception:
                pass
            return task

    def pause(self, task_id: str, user_id: int, db: Session | None = None) -> DownloadTaskRecord | None:
        task = self.get(task_id, user_id, db=db)
        if task is None:
            return None
        if task.status not in {"COMPLETED", "FAILED", "CANCELLED"}:
            return self._set_state(task_id, status="PAUSED", progress=int(task.progress or 0), message="Download paused")
        return task

    def resume(self, task_id: str, user_id: int, db: Session | None = None) -> DownloadTaskRecord | None:
        task = self.get(task_id, user_id, db=db)
        if task is None:
            return None
        if task.status == "PAUSED":
            resumed = self._set_state(task_id, status="RUNNING", progress=int(task.progress or 0), message="Download resumed")
            self._schedule(task_id)
            return resumed
        return task

    def restart(self, task_id: str, user_id: int, db: Session | None = None) -> DownloadTaskRecord | None:
        task = self.get(task_id, user_id, db=db)
        if task is None:
            return None
        repo_id = task.repo_id
        filename = task.filename
        self._set_state(task_id, status="CANCELLED", progress=int(task.progress or 0), message="Restarted as a new download", completed=True)
        target = self._target_path(repo_id)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return self.start(repo_id, user_id, filename, db=db)

    async def _run(self, task_id: str) -> None:
        await asyncio.to_thread(self._semaphore.acquire)
        try:
            await asyncio.to_thread(self._run_sync, task_id)
        finally:
            self._semaphore.release()
            with self._active_lock:
                self._active.discard(task_id)

    def _run_sync(self, task_id: str) -> None:
        task = self._set_state(task_id, status="RUNNING", progress=0, message="Download started")
        if task is None:
            return
        try:
            endpoint = (settings.hf_endpoint or "").strip().rstrip("/")
            if endpoint:
                os.environ["HF_ENDPOINT"] = endpoint
            target = self._target_path(task.repo_id)
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            files = self._resolve_files(task.repo_id, task.filename)
            if not files:
                raise RuntimeError("No downloadable files matched the request")
            self._download_files(task_id, files, target)
            self._set_state(task_id, status="COMPLETED", progress=100, message="Download completed", completed=True)
        except DownloadCancelled:
            current = self.get(task_id, task.user_id)
            self._set_state(
                task_id,
                status="CANCELLED",
                progress=int(current.progress if current else task.progress or 0),
                message="Download cancelled",
                completed=True,
            )
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

    def _resolve_files(self, repo_id: str, filename: str | None = None) -> list[DownloadFile]:
        from huggingface_hub import HfApi, hf_hub_url

        endpoint = (settings.hf_endpoint or "").strip().rstrip("/") or None
        api = HfApi(endpoint=endpoint) if endpoint else HfApi()
        info = api.model_info(repo_id, files_metadata=True)
        files: list[DownloadFile] = []
        for sibling in getattr(info, "siblings", []) or []:
            path = getattr(sibling, "rfilename", None) or getattr(sibling, "filename", None)
            if not path or path.endswith("/"):
                continue
            if filename and not fnmatch.fnmatch(path, filename):
                continue
            size = getattr(sibling, "size", None)
            url_kwargs = {"repo_id": repo_id, "filename": path}
            if endpoint:
                url_kwargs["endpoint"] = endpoint
            files.append(
                DownloadFile(
                    path=path,
                    size=int(size) if size is not None else None,
                    url=hf_hub_url(**url_kwargs),
                )
            )
        return files

    def _download_files(self, task_id: str, files: list[DownloadFile], target: Path) -> None:
        total = sum(item.size or 0 for item in files)
        progress = {
            "downloaded": sum(self._completed_bytes(target / item.path, item.size) for item in files),
            "total": total,
            "last_percent": -1,
            "last_update": 0.0,
        }
        progress_lock = threading.Lock()
        self._publish_progress(task_id, progress, progress_lock, force=True)
        with ThreadPoolExecutor(max_workers=min(self._workers, len(files))) as pool:
            futures = [pool.submit(self._download_one, task_id, item, target, progress, progress_lock) for item in files]
            for future in as_completed(futures):
                future.result()

    def _download_one(self, task_id: str, spec: DownloadFile, target: Path, progress: dict[str, Any], progress_lock: threading.Lock) -> None:
        import httpx

        destination = target / spec.path
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        existing = destination.stat().st_size if destination.exists() else 0
        if spec.size is not None and existing >= spec.size:
            return
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        timeout = httpx.Timeout(connect=20.0, read=60.0, write=60.0, pool=20.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", spec.url, headers=headers) as response:
                if existing and response.status_code == 200:
                    self._adjust_progress(progress, progress_lock, -existing)
                    existing = 0
                elif response.status_code == 416 and spec.size is not None and destination.exists() and destination.stat().st_size >= spec.size:
                    return
                response.raise_for_status()
                mode = "ab" if existing and response.status_code == 206 else "wb"
                with destination.open(mode + "") as handle:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        self._wait_if_paused_or_cancelled(task_id)
                        handle.write(chunk)
                        self._adjust_progress(progress, progress_lock, len(chunk))
                        self._publish_progress(task_id, progress, progress_lock)

    def _wait_if_paused_or_cancelled(self, task_id: str) -> None:
        while True:
            download_status, task_status = self._control_status(task_id)
            if download_status in {"CANCELLED", "FAILED"} or task_status == "CANCEL_REQUESTED":
                raise DownloadCancelled()
            if download_status != "PAUSED":
                return
            time.sleep(0.5)

    def _control_status(self, task_id: str) -> tuple[str | None, str | None]:
        with SessionLocal() as session:
            task = session.get(DownloadTaskRecord, task_id)
            task_record = (
                session.query(TaskRecord)
                .filter_by(source="model_download", source_task_id=task_id)
                .first()
            )
            return (task.status if task else None, task_record.status if task_record else None)

    def _adjust_progress(self, progress: dict[str, Any], progress_lock: threading.Lock, delta: int) -> None:
        with progress_lock:
            progress["downloaded"] = max(0, int(progress["downloaded"]) + delta)

    def _publish_progress(self, task_id: str, progress: dict[str, Any], progress_lock: threading.Lock, *, force: bool = False) -> None:
        download_status, task_status = self._control_status(task_id)
        if download_status in {"CANCELLED", "FAILED"} or task_status == "CANCEL_REQUESTED":
            raise DownloadCancelled()
        if download_status == "PAUSED":
            return
        with progress_lock:
            total = int(progress["total"] or 0)
            downloaded = int(progress["downloaded"] or 0)
            percent = int(downloaded * 100 / total) if total else 1
            now = time.monotonic()
            if not force and percent == progress["last_percent"] and now - float(progress["last_update"] or 0.0) < 1.0:
                return
            progress["last_percent"] = percent
            progress["last_update"] = now
        message = f"Download in progress · {self._format_bytes(downloaded)} / {self._format_bytes(total)}" if total else "Download in progress"
        self._set_state(task_id, status="RUNNING", progress=max(1, min(99, percent)), message=message)

    @staticmethod
    def _completed_bytes(path: Path, expected_size: int | None) -> int:
        if not path.exists():
            return 0
        size = path.stat().st_size
        return min(size, expected_size) if expected_size is not None else 0

    @staticmethod
    def _format_bytes(value: int) -> str:
        amount = float(max(0, value))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if amount < 1024 or unit == "TB":
                return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
            amount /= 1024
        return f"{amount:.1f} TB"

    @staticmethod
    def _target_path(repo_id: str) -> Path:
        return Path(settings.model_dir) / repo_id.replace("/", "_")

    def _project_task(self, task: DownloadTaskRecord, db: Session | None = None) -> None:
        from services.task_realtime import task_outbox_publisher
        from services.task_service import TERMINAL, TaskService

        status = {
            "PENDING": "QUEUED",
            "RUNNING": "RUNNING",
            "PAUSED": "PAUSED",
            "COMPLETED": "SUCCEEDED",
            "FAILED": "FAILED",
            "CANCELLED": "CANCELLED",
        }.get(task.status or "PENDING", "RUNNING")
        target_path = self._target_path(task.repo_id)
        metadata = {"repo_id": task.repo_id, "filename": task.filename, "local_path": str(target_path)}
        result = {"repo_id": task.repo_id, "local_path": str(target_path)} if status == "SUCCEEDED" else None
        service = TaskService()
        owns_session = db is None
        session = db or SessionLocal()
        try:
            projected = service.project(
                session,
                user_id=task.user_id,
                task_type="model_download",
                source="model_download",
                source_task_id=task.id,
                title=f"模型下载：{task.repo_id}",
                status=status,
                summary=task.message,
                progress_percent=int(task.progress or 0),
                cancelable=status not in TERMINAL,
                retryable=status in {"FAILED", "CANCELLED"},
                metadata=metadata,
            )
            if result is not None and projected.result is None:
                service.transition(session, projected, status, result=result)
            task_outbox_publisher.nudge()
        finally:
            if owns_session:
                session.close()

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

        provider = HFProvider(endpoint=settings.hf_endpoint)
        results = provider.list_models(query or "gguf", limit=limit)
        if author:
            results = [item for item in results if author.lower() in str(item.get("author", "")).lower()]
        return results


downloader = Downloader()


def get_downloader() -> Downloader:
    return downloader
