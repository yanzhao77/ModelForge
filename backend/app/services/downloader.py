"""User-scoped, persistent model download task service."""
from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from core.config import settings
from core.database import SessionLocal
from models.records import DownloadTaskRecord, TaskRecord
from sqlalchemy.orm import Session


class DownloadCancelled(Exception):
    """Raised internally when a task-center cancel reaches the downloader."""


class DownloadIntegrityError(Exception):
    """Raised when downloaded bytes do not match the upstream size or hash."""


@dataclass(frozen=True)
class DownloadFile:
    path: str
    size: int | None
    url: str
    sha256: str | None = None
    revision: str | None = None


@dataclass
class _FileTask:
    """Immutable-ish context shared by one file inside a download task."""

    task_id: str
    target: Path
    destination: Path
    progress: dict[str, Any]
    progress_lock: threading.Lock
    manifest: dict[str, Any]
    manifest_lock: threading.Lock


class Downloader:
    """Persist download state before dispatching background work.

    The process still performs the actual download locally, but the task record
    is a durable source of truth. A process restart therefore yields an honest
    PENDING/RUNNING status rather than exposing another user's in-memory task.
    """

    #: Per-repository resume/verification state. It never leaves the model dir.
    MANIFEST_NAME = ".modelforge-download.json"

    def __init__(self, *, max_downloads: int = 2, workers: int = 4, attempts: int = 3):
        self._semaphore = threading.BoundedSemaphore(max_downloads)
        self._workers = max(1, workers)
        self._attempts = max(1, attempts)
        self._active: set[str] = set()
        self._active_lock = threading.Lock()
        self._cancels: dict[str, threading.Event] = {}
        self._control_cache: dict[str, tuple[float, str | None, str | None]] = {}
        self._control_lock = threading.Lock()
        self._control_ttl = 0.5

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
            self._cancels[task_id] = threading.Event()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            threading.Thread(
                target=lambda: asyncio.run(self._run(task_id)), daemon=True
            ).start()
        else:
            loop.create_task(self._run(task_id))

    def _register_worker(self, task_id: str) -> threading.Event:
        """Make sure a running worker has a cancel flag and is marked active."""
        with self._active_lock:
            event = self._cancels.get(task_id)
            if event is None:
                event = threading.Event()
                self._cancels[task_id] = event
            self._active.add(task_id)
        return event

    def _cancel_event(self, task_id: str) -> threading.Event:
        """In-memory cancel flag; an unset throwaway when the task is not active."""
        with self._active_lock:
            event = self._cancels.get(task_id)
        return event if event is not None else threading.Event()

    def _request_cancel(self, task_id: str) -> None:
        """Signal a worker to stop before its next chunk."""
        with self._active_lock:
            event = self._cancels.get(task_id)
        if event is not None:
            event.set()

    def _stop_worker(self, task_id: str, timeout: float = 15.0) -> bool:
        """Wait for a worker to leave the active set so its files can be removed."""
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            with self._active_lock:
                if task_id not in self._active:
                    return True
            time.sleep(0.05)
        with self._active_lock:
            return task_id not in self._active

    def _forget_control_status(self, task_id: str) -> None:
        with self._control_lock:
            self._control_cache.pop(task_id, None)

    @staticmethod
    def _load_record(task_id: str) -> DownloadTaskRecord | None:
        with SessionLocal() as session:
            return session.get(DownloadTaskRecord, task_id)

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
            self._forget_control_status(task_id)
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
        progress = int(task.progress or 0)
        # Stop the running worker before touching its files: deleting a directory
        # that another thread is still writing leaves half-written resume state.
        self._request_cancel(task_id)
        self._set_state(task_id, status="CANCELLED", progress=progress, message="Restarted as a new download", completed=True)
        if self._stop_worker(task_id):
            target = self._target_path(repo_id)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        return self.start(repo_id, user_id, filename, db=db)

    async def _run(self, task_id: str) -> None:
        self._register_worker(task_id)
        await asyncio.to_thread(self._semaphore.acquire)
        try:
            await asyncio.to_thread(self._run_sync, task_id)
        finally:
            self._semaphore.release()
            with self._active_lock:
                self._active.discard(task_id)
                self._cancels.pop(task_id, None)
            self._forget_control_status(task_id)

    def _run_sync(self, task_id: str) -> None:
        if self._cancel_event(task_id).is_set():
            self._settle_cancelled(task_id)
            return
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
            self._settle_cancelled(task_id, fallback_progress=int(task.progress or 0))
        except DownloadIntegrityError:
            # Separate code from connectivity failures: the local bytes are
            # wrong, so a plain retry would re-use the same corrupt file.
            self._set_state(
                task_id,
                status="FAILED",
                progress=0,
                message="Download failed integrity verification",
                error_code="MODEL_DOWNLOAD_INTEGRITY_FAILED",
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

    def _settle_cancelled(self, task_id: str, fallback_progress: int = 0) -> None:
        """Record a cancellation without clobbering a richer reason."""
        record = self._load_record(task_id)
        if record is not None and record.status == "CANCELLED":
            # restart() already recorded why this run was abandoned.
            return
        progress = int(record.progress or 0) if record is not None else fallback_progress
        self._set_state(
            task_id,
            status="CANCELLED",
            progress=progress,
            message="Download cancelled",
            completed=True,
        )

    def _resolve_files(self, repo_id: str, filename: str | None = None) -> list[DownloadFile]:
        from huggingface_hub import HfApi, hf_hub_url

        endpoint = (settings.hf_endpoint or "").strip().rstrip("/") or None
        api = HfApi(endpoint=endpoint) if endpoint else HfApi()
        info = api.model_info(repo_id, files_metadata=True)
        revision = self._as_text(getattr(info, "sha", None))
        files: list[DownloadFile] = []
        for sibling in getattr(info, "siblings", []) or []:
            path = getattr(sibling, "rfilename", None) or getattr(sibling, "filename", None)
            if not path or path.endswith("/"):
                continue
            if PurePosixPath(path).name == self.MANIFEST_NAME:
                continue
            if filename and not fnmatch.fnmatch(path, filename):
                continue
            lfs = getattr(sibling, "lfs", None)
            url_kwargs = {"repo_id": repo_id, "filename": path}
            if endpoint:
                url_kwargs["endpoint"] = endpoint
            files.append(
                DownloadFile(
                    path=path,
                    size=self._as_size(getattr(sibling, "size", None)),
                    url=hf_hub_url(**url_kwargs),
                    sha256=self._as_text(getattr(lfs, "sha256", None)),
                    revision=revision,
                )
            )
        return files

    @staticmethod
    def _as_text(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _as_size(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _manifest_path(cls, target: Path) -> Path:
        return target / cls.MANIFEST_NAME

    @classmethod
    def _load_manifest(cls, target: Path) -> dict[str, Any]:
        try:
            payload = json.loads(cls._manifest_path(target).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _write_manifest(cls, target: Path, manifest: dict[str, Any]) -> None:
        """Persist resume/verification state; never fail a download over it."""
        try:
            cls._manifest_path(target).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    @staticmethod
    def _entry_matches(entry: dict[str, Any], item: DownloadFile) -> bool:
        if entry.get("size") != item.size:
            return False
        if (entry.get("sha256") or None) != (item.sha256 or None):
            return False
        recorded_revision = entry.get("revision") or None
        if item.revision and recorded_revision and recorded_revision != item.revision:
            return False
        return True

    @staticmethod
    def _safe_destination(target: Path, relative_path: str) -> Path:
        """Resolve a repository file path inside the model directory only."""
        if not relative_path or not relative_path.strip():
            raise DownloadIntegrityError("unsafe repository path: empty")
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
            raise DownloadIntegrityError(f"unsafe repository path: {relative_path}")
        root = target.resolve()
        destination = (target / relative_path).resolve()
        if not destination.is_relative_to(root):
            raise DownloadIntegrityError(f"unsafe repository path: {relative_path}")
        return destination

    def _download_files(self, task_id: str, files: list[DownloadFile], target: Path) -> None:
        # Validate every path before any worker starts writing.
        destinations = {item.path: self._safe_destination(target, item.path) for item in files}
        total = sum(item.size or 0 for item in files)
        progress = {
            "downloaded": sum(self._completed_bytes(destinations[item.path], item.size) for item in files),
            "total": total,
            "last_percent": -1,
            "last_update": 0.0,
        }
        progress_lock = threading.Lock()
        manifest = self._load_manifest(target)
        if not isinstance(manifest.get("files"), dict):
            # A truncated or hand-edited state file must never break a download.
            manifest["files"] = {}
        manifest_lock = threading.Lock()
        self._invalidate_stale_partials(files, destinations, manifest, progress, progress_lock)
        self._publish_progress(task_id, progress, progress_lock, force=True)
        with ThreadPoolExecutor(max_workers=min(self._workers, len(files))) as pool:
            futures = [
                pool.submit(
                    self._download_one,
                    item,
                    _FileTask(
                        task_id=task_id,
                        target=target,
                        destination=destinations[item.path],
                        progress=progress,
                        progress_lock=progress_lock,
                        manifest=manifest,
                        manifest_lock=manifest_lock,
                    ),
                )
                for item in files
            ]
            for future in as_completed(futures):
                future.result()

    def _invalidate_stale_partials(
        self,
        files: list[DownloadFile],
        destinations: dict[str, Path],
        manifest: dict[str, Any],
        progress: dict[str, Any],
        progress_lock: threading.Lock,
    ) -> None:
        """Drop partial files whose recorded upstream identity no longer matches.

        Splicing bytes from two revisions of a repository yields a file with the
        correct length and corrupt content, which is worse than starting over.
        Files with no manifest entry keep the legacy size-based resume path.
        """
        recorded = manifest.get("files") or {}
        for item in files:
            entry = recorded.get(item.path)
            if not isinstance(entry, dict) or self._entry_matches(entry, item):
                continue
            destination = destinations[item.path]
            if not destination.exists():
                continue
            self._adjust_progress(progress, progress_lock, -self._completed_bytes(destination, item.size))
            try:
                destination.unlink()
            except OSError:
                pass

    def _download_one(self, spec: DownloadFile, file_task: _FileTask) -> None:
        destination = file_task.destination
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        recorded = file_task.manifest.get("files") or {}
        entry = recorded.get(spec.path)
        verified = (
            isinstance(entry, dict)
            and self._entry_matches(entry, spec)
            and bool(entry.get("verified"))
        )
        existing = destination.stat().st_size if destination.exists() else 0
        if spec.size is not None and existing >= spec.size:
            if verified:
                return
            # A full-length file from an older run was never hash-checked.
            self._verify_file(spec, file_task)
            self._remember_verified(spec, file_task)
            return
        self._transfer_with_retries(spec, file_task, existing)
        self._verify_file(spec, file_task)
        self._remember_verified(spec, file_task)

    def _transfer_with_retries(self, spec: DownloadFile, file_task: _FileTask, existing: int) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            if attempt > 1:
                # Transient upstream failures should not cost the whole download.
                self._sleep_with_cancel(file_task.task_id, min(2 ** (attempt - 1), 8) * 0.5)
                existing = file_task.destination.stat().st_size if file_task.destination.exists() else 0
                if spec.size is not None and existing >= spec.size:
                    return
            try:
                self._transfer(spec, file_task, existing)
                return
            except (DownloadCancelled, DownloadIntegrityError):
                raise
            except Exception as error:
                last_error = error
                if not self._retryable(error):
                    raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("Download attempt failed")

    @staticmethod
    def _retryable(error: Exception) -> bool:
        if isinstance(error, httpx.TransportError):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            return status == 429 or status >= 500
        return False

    def _sleep_with_cancel(self, task_id: str, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self._wait_if_paused_or_cancelled(task_id)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._cancel_event(task_id).wait(min(0.5, remaining))

    def _transfer(self, spec: DownloadFile, file_task: _FileTask, existing: int) -> None:
        task_id = file_task.task_id
        destination = file_task.destination
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        timeout = httpx.Timeout(connect=20.0, read=60.0, write=60.0, pool=20.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", spec.url, headers=headers) as response:
                if existing and response.status_code == 200:
                    # The upstream ignored Range: restart this file from byte zero.
                    self._adjust_progress(file_task.progress, file_task.progress_lock, -existing)
                    existing = 0
                elif response.status_code == 416 and spec.size is not None and destination.exists() and destination.stat().st_size >= spec.size:
                    return
                response.raise_for_status()
                mode = "ab" if existing and response.status_code == 206 else "wb"
                with destination.open(mode) as handle:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        self._wait_if_paused_or_cancelled(task_id)
                        handle.write(chunk)
                        self._adjust_progress(file_task.progress, file_task.progress_lock, len(chunk))
                        self._publish_progress(task_id, file_task.progress, file_task.progress_lock)

    def _verify_file(self, spec: DownloadFile, file_task: _FileTask) -> None:
        """Compare the local bytes with the upstream size and LFS hash."""
        destination = file_task.destination
        size = destination.stat().st_size if destination.exists() else 0
        if spec.size is not None and size != spec.size:
            self._discard_unverified(spec, file_task)
            raise DownloadIntegrityError(f"size mismatch for {spec.path}")
        if not spec.sha256:
            return
        digest = hashlib.sha256()
        with destination.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                self._wait_if_paused_or_cancelled(file_task.task_id)
                digest.update(block)
        if digest.hexdigest() != spec.sha256:
            self._discard_unverified(spec, file_task)
            raise DownloadIntegrityError(f"sha256 mismatch for {spec.path}")

    def _discard_unverified(self, spec: DownloadFile, file_task: _FileTask) -> None:
        """Remove bytes that failed verification so the next run re-downloads them."""
        destination = file_task.destination
        self._adjust_progress(
            file_task.progress, file_task.progress_lock, -self._completed_bytes(destination, spec.size)
        )
        try:
            destination.unlink()
        except OSError:
            pass

    def _remember_verified(self, spec: DownloadFile, file_task: _FileTask) -> None:
        with file_task.manifest_lock:
            files = file_task.manifest.setdefault("files", {})
            files[spec.path] = {
                "size": spec.size,
                "sha256": spec.sha256,
                "revision": spec.revision,
                "verified": True,
            }
            self._write_manifest(file_task.target, file_task.manifest)

    def _wait_if_paused_or_cancelled(self, task_id: str) -> None:
        event = self._cancel_event(task_id)
        while True:
            if event.is_set():
                raise DownloadCancelled()
            download_status, task_status = self._control_status(task_id)
            if download_status in {"CANCELLED", "FAILED"} or task_status == "CANCEL_REQUESTED":
                raise DownloadCancelled()
            if download_status != "PAUSED":
                return
            event.wait(0.5)

    def _control_status(self, task_id: str) -> tuple[str | None, str | None]:
        """Read download/task-center status with a short cache.

        Workers ask for this before every 1 MiB chunk and again when publishing
        progress; without the cache a single large model turns into hundreds of
        redundant queries per second per worker.
        """
        now = time.monotonic()
        with self._control_lock:
            cached = self._control_cache.get(task_id)
            if cached is not None and now - cached[0] < self._control_ttl:
                return cached[1], cached[2]
        with SessionLocal() as session:
            task = session.get(DownloadTaskRecord, task_id)
            task_record = (
                session.query(TaskRecord)
                .filter_by(source="model_download", source_task_id=task_id)
                .first()
            )
            download_status = task.status if task else None
            task_status = task_record.status if task_record else None
        with self._control_lock:
            self._control_cache[task_id] = (now, download_status, task_status)
        return download_status, task_status

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
