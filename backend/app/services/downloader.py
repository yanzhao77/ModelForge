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


class DownloadDiskSpaceError(Exception):
    """Raised when the model directory cannot fit the planned download."""


class DownloadPaused(Exception):
    """Raised internally when the user pauses a running download."""


class _ResumeMismatch(Exception):
    """Upstream answered a Range request from an offset we did not ask for."""


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
    is a durable source of truth. A process restart therefore reconciles
    leftover rows to PAUSED rather than exposing another user's in-memory task.
    """

    #: Per-repository resume/verification state. It never leaves the model dir.
    MANIFEST_NAME = ".modelforge-download.json"
    TASK_PLAN_DIR = "model_download_tasks"

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
        # Bytes are shared, not duplicated per user, so transfers into the same
        # physical model directory are serialized instead of isolated.
        self._repo_locks: dict[str, threading.Lock] = {}
        self._repo_locks_guard = threading.Lock()

    def start(
        self,
        repo_id: str,
        user_id: int,
        filename: str | None = None,
        *,
        files: list[str] | None = None,
        include_support_files: bool = True,
        full_repository: bool = False,
        db: Session | None = None,
    ) -> DownloadTaskRecord:
        repo_id = str(repo_id).strip().strip("/")
        filename = str(filename).strip() if filename else None
        cleaned_files = [str(item).strip() for item in (files or []) if str(item).strip()]
        session = db or SessionLocal()
        existing = self._find_duplicate(
            user_id,
            repo_id,
            filename=filename,
            files=cleaned_files,
            include_support_files=include_support_files,
            full_repository=full_repository,
            db=session,
        )
        if existing is not None:
            if existing.status in {"PENDING", "RUNNING"}:
                self._schedule(existing.id)
            if db is None:
                session.close()
            return existing
        task = DownloadTaskRecord(
            id=uuid.uuid4().hex,
            user_id=user_id,
            repo_id=repo_id,
            filename=filename or ("完整仓库" if full_repository else (", ".join(cleaned_files[:2])[:500] if cleaned_files else None)),
            status="PENDING",
            progress=0,
            message="Pending",
        )
        try:
            session.add(task)
            session.commit()
            session.refresh(task)
            self._write_task_plan(
                task.id,
                {
                    "repo_id": repo_id,
                    "filename": filename,
                    "files": cleaned_files,
                    "include_support_files": bool(include_support_files),
                    "full_repository": bool(full_repository),
                },
            )
        except Exception:
            session.rollback()
            raise
        finally:
            if db is None:
                session.close()
        self._schedule(task.id)
        return task

    def _find_duplicate(
        self,
        user_id: int,
        repo_id: str,
        *,
        filename: str | None,
        files: list[str],
        include_support_files: bool,
        full_repository: bool,
        db: Session | None = None,
    ) -> DownloadTaskRecord | None:
        session = db or SessionLocal()
        try:
            rows = (
                session.query(DownloadTaskRecord)
                .filter_by(user_id=user_id, repo_id=repo_id)
                .filter(DownloadTaskRecord.status.in_(("PENDING", "RUNNING", "PAUSED")))
                .order_by(DownloadTaskRecord.created_at.desc())
                .all()
            )
            wanted = {
                "repo_id": repo_id,
                "filename": filename,
                "files": files,
                "include_support_files": bool(include_support_files),
                "full_repository": bool(full_repository),
            }
            for row in rows:
                plan = self._read_task_plan(row.id)
                legacy_match = not plan and row.filename == filename and not files and not full_repository
                if legacy_match or plan == wanted:
                    return row
            return None
        finally:
            if db is None:
                session.close()

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

    def reconcile_orphaned_tasks(self) -> int:
        """Settle downloads left mid-flight by a previous process.

        Workers only live in memory, so after a restart every non-terminal row
        is an orphan. Marking them PAUSED keeps the task center honest and lets
        the user continue from the bytes still on disk, while a cancel that was
        requested before the restart is settled instead of hanging forever.
        """
        with self._active_lock:
            active = set(self._active)
        settled: list[str] = []
        with SessionLocal() as session:
            rows = (
                session.query(DownloadTaskRecord)
                .filter(DownloadTaskRecord.status.in_(("PENDING", "RUNNING", "PAUSED")))
                .all()
            )
            orphans = [row for row in rows if row.id not in active]
            cancel_requested: set[str] = set()
            if orphans:
                cancel_requested = {
                    task_id
                    for (task_id,) in session.query(TaskRecord.source_task_id)
                    .filter(TaskRecord.source.in_(("model_download", "download")))
                    .filter(TaskRecord.source_task_id.in_([row.id for row in orphans]))
                    .filter(TaskRecord.status == "CANCEL_REQUESTED")
                    .all()
                }
            for row in orphans:
                if row.id in cancel_requested:
                    row.status = "CANCELLED"
                    row.message = "Download cancelled after restart"
                    row.completed_at = datetime.utcnow()
                elif row.status != "PAUSED":
                    row.status = "PAUSED"
                    row.message = "Download interrupted by restart; resume to continue"
                row.error_code = None
                settled.append(row.id)
            session.commit()
        for task_id in settled:
            record = self._load_record(task_id)
            if record is None:
                continue
            try:
                self._project_task(record)
            except Exception:
                # A projection failure must never block startup.
                pass
        return len(settled)

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
        """Wait for a worker to leave the active set before shared state is touched."""
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            with self._active_lock:
                if task_id not in self._active:
                    return True
            time.sleep(0.05)
        with self._active_lock:
            return task_id not in self._active

    def _repo_has_other_active_task(self, repo_id: str, exclude_task_id: str) -> bool:
        """True when another live worker is already writing this repository."""
        with self._active_lock:
            others = [task_id for task_id in self._active if task_id != exclude_task_id]
        if not others:
            return False
        with SessionLocal() as session:
            return (
                session.query(DownloadTaskRecord.id)
                .filter(DownloadTaskRecord.id.in_(others))
                .filter(DownloadTaskRecord.repo_id == repo_id)
                .first()
                is not None
            )

    def _repo_lock(self, target: Path) -> threading.Lock:
        """Return the per-target mutex that guards shared model bytes."""
        key = str(target.resolve())
        with self._repo_locks_guard:
            lock = self._repo_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._repo_locks[key] = lock
        return lock

    def _current_progress(self, task_id: str) -> int:
        try:
            record = self._load_record(task_id)
        except Exception:
            return 0
        return int(record.progress or 0) if record is not None else 0

    def _forget_control_status(self, task_id: str) -> None:
        with self._control_lock:
            self._control_cache.pop(task_id, None)

    @staticmethod
    def _load_record(task_id: str) -> DownloadTaskRecord | None:
        try:
            with SessionLocal() as session:
                return session.get(DownloadTaskRecord, task_id)
        except Exception:
            return None

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

    def cancel(self, task_id: str, user_id: int, db: Session | None = None) -> DownloadTaskRecord | None:
        task = self.get(task_id, user_id, db=db)
        if task is None:
            return None
        if task.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return task
        self._request_cancel(task_id)
        return self._set_state(
            task_id,
            status="CANCELLED",
            progress=int(task.progress or 0),
            message="Download cancelled",
            completed=True,
        )

    def resume(self, task_id: str, user_id: int, db: Session | None = None) -> DownloadTaskRecord | None:
        task = self.get(task_id, user_id, db=db)
        if task is None:
            return None
        if task.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return task
        # A live worker unblocks as soon as the row leaves PAUSED; an orphan left
        # behind by a previous process is rescheduled and Range-resumes from the
        # bytes still on disk. ``_schedule`` is idempotent, so a live worker is
        # never started twice.
        resumed = self._set_state(
            task_id, status="RUNNING", progress=int(task.progress or 0), message="Download resumed"
        )
        self._schedule(task_id)
        return resumed

    def restart(self, task_id: str, user_id: int, db: Session | None = None) -> DownloadTaskRecord | None:
        """Cancel the current run and re-verify what is already on disk.

        The destination directory is shared by every user and task that
        resolves the same repository, so a restart must never wipe it. Dropping
        the verified marks instead forces a fresh hash check of the local bytes;
        only corrupt or incomplete files are fetched again.
        """
        task = self.get(task_id, user_id, db=db)
        if task is None:
            return None
        repo_id = task.repo_id
        plan = self._read_task_plan(task_id)
        filename = self._as_text(plan.get("filename")) or task.filename
        progress = int(task.progress or 0)
        # Stop the running worker before touching shared resume state.
        self._request_cancel(task_id)
        self._set_state(
            task_id, status="CANCELLED", progress=progress, message="Restarted as a new download", completed=True
        )
        stopped = self._stop_worker(task_id)
        if stopped and not self._repo_has_other_active_task(repo_id, task_id):
            self._invalidate_verification_state(self._target_path(repo_id))
        if plan:
            return self.start(
                repo_id,
                user_id,
                filename,
                files=list(plan.get("files") or []),
                include_support_files=bool(plan.get("include_support_files", True)),
                full_repository=bool(plan.get("full_repository")),
                db=db,
            )
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
            # A pause makes this worker exit so the download slot is released;
            # if the user resumed in the meantime, start a fresh worker.
            self._resume_if_still_running(task_id)

    def _resume_if_still_running(self, task_id: str) -> None:
        record = self._load_record(task_id)
        if record is not None and record.status == "RUNNING":
            self._schedule(task_id)

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
            plan = self._read_task_plan(task_id)
            files = (
                self._resolve_files(task.repo_id, task.filename, task_id=task_id)
                if plan
                else self._resolve_files(task.repo_id, task.filename)
            )
            if not files:
                raise RuntimeError("No downloadable files matched the request")
            self._download_files(task_id, files, target)
            self._set_state(task_id, status="COMPLETED", progress=100, message="Download completed", completed=True)
            # Registration is best-effort and runs after the task is durable: a
            # model that does not register must never turn a finished download
            # into a failed one.
            self._register_completed_download(task_id)
        except DownloadCancelled:
            self._settle_cancelled(task_id, fallback_progress=int(task.progress or 0))
        except DownloadPaused:
            # pause() already persisted PAUSED; keep whatever progress the
            # worker published and let resume() start a fresh worker.
            record = self._load_record(task_id)
            if record is not None and record.status == "PAUSED":
                self._set_state(
                    task_id,
                    status="PAUSED",
                    progress=int(record.progress or 0),
                    message="Download paused",
                )
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
        except DownloadDiskSpaceError:
            self._set_state(
                task_id,
                status="FAILED",
                progress=int(task.progress or 0),
                message="Insufficient disk space for selected files",
                error_code="MODEL_DOWNLOAD_DISK_FULL",
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

    def _register_completed_download(self, task_id: str) -> None:
        """Auto-register a completed download into the unified model registry.

        The download service is not a second registry: it hands the finished
        bytes to :class:`ModelRegistry`, which owns capability detection and
        duplicate protection.
        """
        try:
            from services.model_registry import ModelRegistry

            with SessionLocal() as session:
                task = session.get(DownloadTaskRecord, task_id)
                if task is None:
                    return
                ModelRegistry(session).register_download(
                    user_id=task.user_id,
                    repo_id=task.repo_id,
                    target=self._target_path(task.repo_id),
                    filename=self._as_text(self._read_task_plan(task_id).get("filename")),
                )
        except Exception:
            # A registration failure leaves the bytes on disk; a later scan
            # re-discovers them, so the download itself still succeeded.
            return

    def _resolve_files(self, repo_id: str, filename: str | None = None, *, task_id: str | None = None) -> list[DownloadFile]:
        from huggingface_hub import HfApi, hf_hub_url

        endpoint = (settings.hf_endpoint or "").strip().rstrip("/") or None
        api = HfApi(endpoint=endpoint) if endpoint else HfApi()
        info = api.model_info(repo_id, files_metadata=True)
        revision = self._as_text(getattr(info, "sha", None))
        plan = self._read_task_plan(task_id) if task_id else {}
        selected = set(str(item).strip() for item in (plan.get("files") or []) if str(item).strip())
        has_plan = bool(plan)
        full_repository = bool(plan.get("full_repository")) if has_plan else not filename
        include_support = bool(plan.get("include_support_files", True))
        explicit_filename = self._as_text(plan.get("filename")) or filename
        siblings = list(getattr(info, "siblings", []) or [])
        support_files: set[str] = set()
        for sibling in siblings:
            path = self._sibling_path(sibling)
            if path and self._is_support_file(path, self._as_size(getattr(sibling, "size", None))):
                support_files.add(path)
        files: list[DownloadFile] = []
        for sibling in siblings:
            path = self._sibling_path(sibling)
            if not path or path.endswith("/"):
                continue
            if PurePosixPath(path).name == self.MANIFEST_NAME:
                continue
            if not full_repository:
                if selected:
                    if path not in selected and not (include_support and path in support_files):
                        continue
                elif explicit_filename and not fnmatch.fnmatch(path, explicit_filename):
                    continue
                elif has_plan and not explicit_filename:
                    # Defensive default for modern calls: full_repository must be
                    # explicit so a blank file selection cannot download every
                    # large variant in a repository by accident.
                    continue
            if self._is_too_large_support_only(path, selected, full_repository):
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
    def _sibling_path(sibling: Any) -> str | None:
        return getattr(sibling, "rfilename", None) or getattr(sibling, "filename", None)

    @staticmethod
    def _is_support_file(path: str, size: int | None = None) -> bool:
        name = PurePosixPath(path).name
        if name in {
            "README.md",
            "config.json",
            "generation_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "vocab.json",
            "vocab.txt",
            "merges.txt",
            "spiece.model",
            "sentencepiece.bpe.model",
            "preprocessor_config.json",
            "processor_config.json",
            "feature_extractor_config.json",
            "image_processor_config.json",
            "model_index.json",
            "scheduler_config.json",
        }:
            return True
        return name.endswith(".json") and (size is None or size < 50 * 1024 * 1024)

    @staticmethod
    def _is_too_large_support_only(path: str, selected: set[str], full_repository: bool) -> bool:
        if full_repository or path in selected:
            return False
        return False

    @classmethod
    def _task_plan_root(cls) -> Path:
        root = Path(settings.database_path).expanduser().resolve().parent / cls.TASK_PLAN_DIR
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return root

    @classmethod
    def _task_plan_path(cls, task_id: str) -> Path:
        safe = "".join(ch for ch in str(task_id) if ch.isalnum() or ch in {"-", "_"})
        return cls._task_plan_root() / f"{safe}.json"

    @classmethod
    def _task_progress_path(cls, task_id: str) -> Path:
        safe = "".join(ch for ch in str(task_id) if ch.isalnum() or ch in {"-", "_"})
        return cls._task_plan_root() / f"{safe}.progress.json"

    @classmethod
    def _write_task_plan(cls, task_id: str, payload: dict[str, Any]) -> None:
        try:
            cls._task_plan_path(task_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    @classmethod
    def _read_task_plan(cls, task_id: str | None) -> dict[str, Any]:
        if not task_id:
            return {}
        try:
            payload = json.loads(cls._task_plan_path(task_id).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _write_task_progress(cls, task_id: str, payload: dict[str, Any]) -> None:
        try:
            cls._task_progress_path(task_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    @classmethod
    def _read_task_progress(cls, task_id: str | None) -> dict[str, Any]:
        if not task_id:
            return {}
        try:
            payload = json.loads(cls._task_progress_path(task_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

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
        path = cls._manifest_path(target)
        temporary = path.with_name(path.name + ".tmp")
        try:
            # Write-then-rename so a crash never leaves a half-written manifest
            # that the next run has to treat as "unknown local state".
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            pass

    @classmethod
    def _invalidate_verification_state(cls, target: Path) -> None:
        """Force the next run to re-hash existing bytes instead of deleting them."""
        manifest = cls._load_manifest(target)
        files = manifest.get("files")
        if not isinstance(files, dict):
            return
        changed = False
        for entry in files.values():
            if isinstance(entry, dict) and entry.get("verified"):
                entry["verified"] = False
                changed = True
        if changed:
            cls._write_manifest(target, manifest)

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
        """Download into a shared model directory, one writer at a time."""
        lock = self._repo_lock(target)
        if not lock.acquire(blocking=False):
            self._set_state(
                task_id,
                status="RUNNING",
                progress=self._current_progress(task_id),
                message="Waiting for another download of this repository",
            )
            # Timeout loop keeps a cancelling task from waiting on the mutex.
            while not lock.acquire(timeout=0.5):
                self._wait_if_paused_or_cancelled(task_id)
        try:
            self._download_files_locked(task_id, files, target)
        finally:
            lock.release()

    def _download_files_locked(self, task_id: str, files: list[DownloadFile], target: Path) -> None:
        # Validate every path before any worker starts writing.
        destinations = {item.path: self._safe_destination(target, item.path) for item in files}
        total = sum(item.size or 0 for item in files)
        progress = {
            "downloaded": sum(self._completed_bytes(destinations[item.path], item.size) for item in files),
            "total": total,
            "last_percent": -1,
            "last_update": 0.0,
            "started_at": time.monotonic(),
            "speed_bps": 0,
        }
        progress_lock = threading.Lock()
        manifest = self._load_manifest(target)
        if not isinstance(manifest.get("files"), dict):
            # A truncated or hand-edited state file must never break a download.
            manifest["files"] = {}
        manifest_lock = threading.Lock()
        self._invalidate_stale_partials(files, destinations, manifest, progress, progress_lock)
        self._check_disk_space(target, progress, progress_lock)
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

    def _check_disk_space(self, target: Path, progress: dict[str, Any], progress_lock: threading.Lock) -> None:
        try:
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            usage = shutil.disk_usage(target)
        except OSError as exc:
            raise DownloadDiskSpaceError("cannot inspect model directory") from exc
        with progress_lock:
            remaining = max(0, int(progress.get("total") or 0) - int(progress.get("downloaded") or 0))
        # Leave a small working margin so metadata and temp files can still be
        # written while the transfer completes.
        if remaining and usage.free < remaining + 128 * 1024 * 1024:
            raise DownloadDiskSpaceError("insufficient disk space")

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
            try:
                self._verify_file(spec, file_task)
            except DownloadIntegrityError:
                # The local bytes are wrong: ``_verify_file`` already removed
                # them, so fetch the file again in this same run.
                existing = 0
            else:
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
            except _ResumeMismatch:
                # Splicing bytes from a different offset would corrupt the file,
                # so drop the partial and fetch this file from byte zero.
                self._discard_unverified(spec, file_task)
                existing = 0
                continue
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

    @staticmethod
    def _range_start(headers) -> int | None:
        """Parse the start offset of an HTTP ``Content-Range`` header."""
        try:
            value = headers.get("Content-Range") if headers is not None else None
        except AttributeError:
            return None
        if not isinstance(value, str):
            return None
        text_value = value.strip().lower()
        if not text_value.startswith("bytes "):
            return None
        span = text_value[6:].split("/", 1)[0]
        start = span.split("-", 1)[0].strip()
        try:
            return int(start)
        except ValueError:
            return None

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
                elif existing and response.status_code == 206:
                    start = self._range_start(getattr(response, "headers", None))
                    if start is not None and start != existing:
                        # Never append bytes that belong at another offset.
                        raise _ResumeMismatch(f"resumed at {start}, expected {existing}")
                elif response.status_code == 416 and spec.size is not None and destination.exists() and destination.stat().st_size >= spec.size:
                    return
                response.raise_for_status()
                mode = "ab" if existing and response.status_code == 206 else "wb"
                # Check before opening the file: "wb" truncates, and a pause
                # right here must not cost the bytes already on disk.
                self._wait_if_paused_or_cancelled(task_id)
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
        """Stop this worker when the task was cancelled or paused.

        Pausing exits the worker instead of waiting in place: the download slot
        is global, so a paused task must not keep it (and its thread) occupied.
        ``resume()`` later starts a fresh worker that continues from disk.
        """
        event = self._cancel_event(task_id)
        if event.is_set():
            raise DownloadCancelled()
        download_status, task_status = self._control_status(task_id)
        if download_status in {"CANCELLED", "FAILED"} or task_status == "CANCEL_REQUESTED":
            raise DownloadCancelled()
        if download_status == "PAUSED":
            raise DownloadPaused()

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
            elapsed = max(0.001, now - float(progress.get("started_at") or now))
            speed = int(downloaded / elapsed)
            progress["speed_bps"] = speed
            if not force and percent == progress["last_percent"] and now - float(progress["last_update"] or 0.0) < 1.0:
                return
            progress["last_percent"] = percent
            progress["last_update"] = now
            eta_seconds = int(max(0, total - downloaded) / speed) if total and speed > 0 else None
        detail = {
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "speed_bps": speed,
            "eta_seconds": eta_seconds,
        }
        self._write_task_progress(task_id, detail)
        eta = f" · ETA {self._format_eta(eta_seconds)}" if eta_seconds is not None else ""
        message = f"Download in progress · {self._format_bytes(downloaded)} / {self._format_bytes(total)} · {self._format_bytes(speed)}/s{eta}" if total else "Download in progress"
        self._set_state(task_id, status="RUNNING", progress=max(1, min(99, percent)), message=message)

    @staticmethod
    def _format_eta(seconds: int | None) -> str:
        if seconds is None:
            return "未知"
        if seconds < 60:
            return f"{seconds}s"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {sec}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"

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

    def to_payload(self, task: DownloadTaskRecord) -> dict:
        payload = task.to_dict()
        progress = self._read_task_progress(task.id)
        if progress:
            payload.update(progress)
            payload["downloaded"] = self._format_bytes(int(progress.get("downloaded_bytes") or 0))
            payload["total"] = self._format_bytes(int(progress.get("total_bytes") or 0))
            payload["speed"] = f"{self._format_bytes(int(progress.get('speed_bps') or 0))}/s"
            eta = progress.get("eta_seconds")
            payload["eta"] = self._format_eta(int(eta)) if eta is not None else "未知"
        plan = self._read_task_plan(task.id)
        if plan:
            payload["plan"] = plan
        payload["local_path"] = str(self._target_path(task.repo_id))
        return payload

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
