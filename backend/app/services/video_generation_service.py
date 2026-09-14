"""Video job persistence, queueing, artifacts, and task projection."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import settings
from core.database import SessionLocal
from models.records import TaskRecord, VideoJob
from services.model_capability_registry import (
    get_capability_registry,
    resolve_video_model,
)
from services.remote_provider_service import ProviderCipher
from services.task_realtime import task_outbox_publisher
from services.task_service import TaskConflict, TaskService
from services.video_runtime import (
    ResolvedVideoGenerationRequest,
    VideoRuntimeError,
    file_sha256,
    resolve_video_request,
)
from sqlalchemy.orm import Session

TERMINAL_VIDEO_STATES = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}


class VideoServiceError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _prompt_cipher() -> ProviderCipher:
    return ProviderCipher(str(settings.data_dir))


def _encrypt_prompt(prompt: str) -> str:
    return _prompt_cipher().encrypt(prompt)


def _decrypt_prompt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    return _prompt_cipher().decrypt(ciphertext)


def _public_id() -> str:
    return f"video_{uuid.uuid4().hex}"


def artifact_root() -> Path:
    root = Path(settings.data_dir).expanduser().resolve() / "video_artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_relative_output(public_id: str) -> str:
    return f"{public_id}/output.mp4"


def resolve_artifact_path(relpath: str) -> Path:
    root = artifact_root()
    path = (root / relpath).resolve()
    if root not in path.parents and path != root:
        raise VideoServiceError("VIDEO_ARTIFACT_MISSING", "Video artifact is unavailable.", status_code=404)
    return path


class VideoGenerationService:
    """Write boundary for VideoJob and its task-center projection."""

    def __init__(self, task_service: TaskService | None = None) -> None:
        self.task_service = task_service or TaskService()

    async def submit(
        self,
        db: Session,
        *,
        user_id: int,
        model_id: str,
        prompt: str,
        seconds: int,
        fps: int,
        size: str,
        num_inference_steps: int | None,
        seed: int | None,
        idempotency_key: str | None,
        correlation_id: str,
    ) -> VideoJob:
        registry = get_capability_registry()
        model = resolve_video_model(db, user_id, model_id)
        if model is None:
            raise VideoServiceError("VIDEO_MODEL_NOT_FOUND", "Video model is unavailable.", status_code=404)
        if model.readiness == "unavailable" and model.readiness_code == "VIDEO_LOAD_VALIDATION_FAILED":
            raise VideoServiceError("VIDEO_MODEL_NOT_READY", model.readiness_reason or "Video model is not ready.", status_code=409)
        runtime = registry.video_runtime(model)
        probe = await runtime.probe(model)
        if not probe.available:
            raise VideoServiceError("VIDEO_MODEL_NOT_READY", "Video model is not ready.", status_code=409)
        try:
            resolved = resolve_video_request(
                model=model,
                prompt=prompt,
                seconds=seconds,
                fps=fps,
                size=size,
                num_inference_steps=num_inference_steps,
                seed=seed,
            )
        except VideoRuntimeError as exc:
            raise VideoServiceError(exc.code, str(exc), status_code=422) from exc

        request_for_hash = {
            "model": model_id,
            "prompt_sha256": resolved.prompt_sha256,
            "seconds": seconds,
            "fps": fps,
            "size": size,
            "num_inference_steps": resolved.num_inference_steps,
            "seed": seed,
        }
        request_hash = _hash_text(_dump(request_for_hash))
        idempotency_hash = _hash_text(idempotency_key) if idempotency_key else None
        if idempotency_hash:
            existing = db.query(VideoJob).filter_by(user_id=user_id, idempotency_key_hash=idempotency_hash).first()
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise VideoServiceError("IDEMPOTENCY_CONFLICT", "Idempotency key was reused with a different request.", status_code=409)
                return existing

        public_id = _public_id()
        task = self.task_service.create(
            db,
            user_id=user_id,
            task_type="video_generation",
            source="video_generation",
            source_task_id=public_id,
            title=f"视频生成：{model.display_name}",
            summary="Queued for video generation.",
            metadata={"video_id": public_id, "model": model_id, "phase": "accepted"},
            cancelable=True,
            retryable=False,
            idempotency_key=f"video:{idempotency_hash}" if idempotency_hash else None,
        )
        task.meta = _dump({"video_id": public_id, "model": model_id, "phase": "accepted"})
        job = VideoJob(
            public_id=public_id,
            user_id=user_id,
            task_id=task.task_id,
            model_id=model_id,
            runtime_name=resolved.runtime_name,
            profile_id=resolved.profile_id,
            status="QUEUED",
            status_detail_code=None,
            progress=0,
            phase="accepted",
            request_json=_dump({k: v for k, v in request_for_hash.items() if k != "prompt_sha256"}),
            resolved_request_json=_dump(resolved.public_dict()),
            prompt_ciphertext=_encrypt_prompt(prompt),
            idempotency_key_hash=idempotency_hash,
            request_hash=request_hash,
            seed=seed,
            frames=resolved.frames,
            fps=resolved.fps,
            width=resolved.width,
            height=resolved.height,
            steps=resolved.num_inference_steps,
            correlation_id=correlation_id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        task_outbox_publisher.nudge()
        get_video_queue().enqueue()
        return job

    def get_for_user(self, db: Session, public_id: str, user_id: int) -> VideoJob | None:
        return db.query(VideoJob).filter_by(public_id=public_id, user_id=user_id).first()

    def content_path(self, job: VideoJob) -> Path:
        if job.status != "COMPLETED":
            raise VideoServiceError("VIDEO_NOT_COMPLETE", "Video is not complete.", status_code=409)
        if not job.output_relpath:
            raise VideoServiceError("VIDEO_ARTIFACT_MISSING", "Video artifact is unavailable.", status_code=404)
        path = resolve_artifact_path(job.output_relpath)
        if not path.is_file():
            raise VideoServiceError("VIDEO_ARTIFACT_MISSING", "Video artifact is unavailable.", status_code=404)
        return path

    def cancel(self, db: Session, job: VideoJob) -> VideoJob:
        now = _utcnow()
        if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return job
        task = db.query(TaskRecord).filter_by(task_id=job.task_id, user_id=job.user_id).first()
        if job.status == "QUEUED":
            job.status = "CANCELLED"
            job.status_detail_code = "cancelled_before_start"
            job.cancelled_at = now
            job.updated_at = now
            if task is not None:
                try:
                    self.task_service.transition(db, task, "CANCELLED", summary="Video generation was cancelled.", progress_percent=job.progress)
                except TaskConflict:
                    db.rollback()
                    db.add(job)
                    db.commit()
            else:
                db.commit()
        elif job.status == "RUNNING":
            job.status = "CANCEL_REQUESTED"
            job.status_detail_code = "cancelling"
            job.updated_at = now
            if task is not None:
                try:
                    self.task_service.transition(db, task, "CANCEL_REQUESTED", summary="Cancelling video generation.", progress_percent=job.progress)
                except TaskConflict:
                    db.rollback()
                    db.add(job)
                    db.commit()
            else:
                db.commit()
        db.refresh(job)
        task_outbox_publisher.nudge()
        get_video_queue().enqueue()
        return job

    def mark_interrupted_jobs(self) -> None:
        db = SessionLocal()
        try:
            jobs = db.query(VideoJob).filter(VideoJob.status.in_(["RUNNING", "CANCEL_REQUESTED"])).all()
            for job in jobs:
                job.status = "INTERRUPTED"
                job.status_detail_code = "startup_reconciliation"
                job.error_code = "VIDEO_INTERRUPTED"
                job.error_summary = "Video generation was interrupted by process restart."
                job.updated_at = _utcnow()
                task = db.query(TaskRecord).filter_by(task_id=job.task_id, user_id=job.user_id).first()
                if task is not None:
                    try:
                        self.task_service.transition(db, task, "FAILED", summary=job.error_summary, error_code=job.error_code, error_message=job.error_summary, progress_percent=job.progress)
                    except TaskConflict:
                        db.rollback()
            db.commit()
        finally:
            db.close()


class VideoQueueCoordinator:
    """Single-process queue coordinator with global video concurrency 1."""

    def __init__(self, service: VideoGenerationService) -> None:
        self.service = service
        self._lock = threading.Lock()
        self._active = False
        self._shutdown = False

    def start(self) -> None:
        self._shutdown = False
        self.service.mark_interrupted_jobs()

    def shutdown(self) -> None:
        self._shutdown = True

    def enqueue(self) -> None:
        with self._lock:
            if self._active or self._shutdown:
                return
            self._active = True
        thread = threading.Thread(target=self._run_loop, name="modelforge-video-queue", daemon=True)
        thread.start()

    def _run_loop(self) -> None:
        try:
            while not self._shutdown:
                public_id = self._claim_next()
                if public_id is None:
                    return
                self._process(public_id)
        finally:
            with self._lock:
                self._active = False
            if not self._shutdown and self._has_queued():
                self.enqueue()

    def _has_queued(self) -> bool:
        db = SessionLocal()
        try:
            return db.query(VideoJob.id).filter_by(status="QUEUED").first() is not None
        finally:
            db.close()

    def _claim_next(self) -> str | None:
        db = SessionLocal()
        try:
            job = db.query(VideoJob).filter_by(status="QUEUED").order_by(VideoJob.queued_at.asc(), VideoJob.id.asc()).first()
            if job is None:
                return None
            job.status = "RUNNING"
            job.phase = "loading"
            job.progress = max(job.progress or 0, 1)
            job.worker_id = uuid.uuid4().hex
            job.started_at = _utcnow()
            job.updated_at = job.started_at
            task = db.query(TaskRecord).filter_by(task_id=job.task_id, user_id=job.user_id).first()
            if task is not None:
                self.service.task_service.transition(db, task, "RUNNING", summary="Starting video generation.", progress_percent=job.progress)
            else:
                db.commit()
            return job.public_id
        finally:
            db.close()

    def _process(self, public_id: str) -> None:
        db = SessionLocal()
        try:
            job = db.query(VideoJob).filter_by(public_id=public_id).first()
            if job is None:
                return
            registry = get_capability_registry()
            model = resolve_video_model(db, job.user_id, job.model_id)
            if model is None:
                self._fail(db, job, "VIDEO_MODEL_NOT_FOUND", "Video model is unavailable.")
                return
            runtime = registry.video_runtime(model)
            try:
                prompt = _decrypt_prompt(job.prompt_ciphertext)
            except Exception:
                self._fail(db, job, "VIDEO_PROMPT_UNAVAILABLE", "Stored video prompt could not be decrypted.")
                return
            if not prompt:
                self._fail(db, job, "VIDEO_PROMPT_UNAVAILABLE", "Stored video prompt is unavailable for this job.")
                return
            resolved = ResolvedVideoGenerationRequest(
                model_id=job.model_id,
                runtime_name=job.runtime_name,
                profile_id=job.profile_id,
                prompt=prompt,
                prompt_sha256=_hash_text(prompt),
                seconds=int(round(job.frames / job.fps)),
                fps=job.fps,
                width=job.width,
                height=job.height,
                frames=job.frames,
                num_inference_steps=job.steps,
                seed=job.seed,
                local_path=model.local_path,
            )
            relpath = _safe_relative_output(job.public_id)
            final_path = resolve_artifact_path(relpath)
            tmp_path = final_path.with_suffix(".tmp")

            async def progress(phase: str, percent: int, total: int | None) -> None:
                del total
                update_db = SessionLocal()
                try:
                    update_job = update_db.query(VideoJob).filter_by(public_id=public_id).first()
                    if update_job is None or update_job.status not in {"RUNNING", "CANCEL_REQUESTED"}:
                        return
                    update_job.phase = phase
                    update_job.progress = max(0, min(100, int(percent)))
                    update_job.updated_at = _utcnow()
                    task = update_db.query(TaskRecord).filter_by(task_id=update_job.task_id, user_id=update_job.user_id).first()
                    if task is not None and task.status == "RUNNING":
                        self.service.task_service.transition(update_db, task, "RUNNING", summary=f"Video phase: {phase}", progress_percent=update_job.progress)
                    else:
                        update_db.commit()
                    task_outbox_publisher.nudge()
                finally:
                    update_db.close()

            def cancelled() -> bool:
                check_db = SessionLocal()
                try:
                    check = check_db.query(VideoJob.status).filter_by(public_id=public_id).first()
                    return bool(check and check[0] == "CANCEL_REQUESTED")
                finally:
                    check_db.close()

            try:
                result = asyncio.run(runtime.generate(resolved, progress=progress, cancellation=cancelled, output_path=tmp_path))
                final_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(result.output_path, final_path)
                sha = file_sha256(final_path)
                stat = final_path.stat()
                self._complete(db, job, relpath, sha, stat.st_size, result.duration_ms)
            except VideoRuntimeError as exc:
                if exc.code == "VIDEO_CANCELLED":
                    self._cancelled(db, job)
                else:
                    self._fail(db, job, exc.code, str(exc))
            except Exception:
                self._fail(db, job, "VIDEO_GENERATION_FAILED", "Video generation failed.")
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        finally:
            db.close()

    def _complete(self, db: Session, job: VideoJob, relpath: str, sha: str, size: int, duration_ms: int) -> None:
        now = _utcnow()
        db.refresh(job)
        if job.status == "CANCEL_REQUESTED":
            self._cancelled(db, job)
            return
        job.status = "COMPLETED"
        job.phase = "complete"
        job.progress = 100
        job.output_relpath = relpath
        job.output_sha256 = sha
        job.output_bytes = size
        job.media_duration_ms = duration_ms
        job.completed_at = now
        job.updated_at = now
        task = db.query(TaskRecord).filter_by(task_id=job.task_id, user_id=job.user_id).first()
        if task is not None:
            self.service.task_service.transition(db, task, "SUCCEEDED", summary="Video generation completed.", progress_percent=100, result={"video_id": job.public_id})
        else:
            db.commit()
        task_outbox_publisher.nudge()

    def _cancelled(self, db: Session, job: VideoJob) -> None:
        now = _utcnow()
        db.refresh(job)
        job.status = "CANCELLED"
        job.status_detail_code = "cancelled"
        job.cancelled_at = now
        job.updated_at = now
        task = db.query(TaskRecord).filter_by(task_id=job.task_id, user_id=job.user_id).first()
        if task is not None:
            self.service.task_service.transition(db, task, "CANCELLED", summary="Video generation was cancelled.", progress_percent=job.progress)
        else:
            db.commit()
        task_outbox_publisher.nudge()

    def _fail(self, db: Session, job: VideoJob, code: str, summary: str) -> None:
        now = _utcnow()
        db.refresh(job)
        job.status = "FAILED"
        job.error_code = code
        job.error_summary = summary
        job.updated_at = now
        job.completed_at = now
        task = db.query(TaskRecord).filter_by(task_id=job.task_id, user_id=job.user_id).first()
        if task is not None:
            self.service.task_service.transition(db, task, "FAILED", summary=summary, error_code=code, error_message=summary, progress_percent=job.progress)
        else:
            db.commit()
        task_outbox_publisher.nudge()


_service = VideoGenerationService()
_queue = VideoQueueCoordinator(_service)


def get_video_service() -> VideoGenerationService:
    return _service


def get_video_queue() -> VideoQueueCoordinator:
    return _queue
