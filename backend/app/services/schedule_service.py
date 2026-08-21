"""Persistent, user-scoped schedule definitions layered on the runtime scheduler."""
from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Callable
from typing import Any

from models.records import ScheduleExecution, ScheduledJob
from sqlalchemy.orm import Session


class ScheduleService:
    """Create explicit schedule drafts and attach them to an AgentRuntime on enable."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _validate(kind: str, delay: float | None, interval: float | None) -> None:
        if kind not in {"once", "interval"}:
            raise ValueError("schedule_kind must be once or interval")
        if kind == "once" and (delay is None or delay <= 0):
            raise ValueError("once schedules require a positive delay_seconds")
        if kind == "interval" and (interval is None or interval < 60):
            raise ValueError("interval schedules require interval_seconds >= 60")

    def create_draft(self, user_id: int, payload: dict[str, Any]) -> ScheduledJob:
        kind = str(payload.get("schedule_kind") or payload.get("type") or "")
        delay = payload.get("delay_seconds")
        interval = payload.get("interval_seconds")
        delay = float(delay) if delay is not None else None
        interval = float(interval) if interval is not None else None
        self._validate(kind, delay, interval)
        agent_id = str(payload.get("agent_id") or "")
        if not agent_id:
            raise ValueError("agent_id required")
        now = datetime.datetime.utcnow()
        next_run = now + datetime.timedelta(seconds=delay) if kind == "once" else now + datetime.timedelta(seconds=interval or 0)
        run_spec = {
            "agent_id": agent_id,
            "input": str(payload.get("input") or ""),
            "session_id": payload.get("session_id"),
            "metadata": payload.get("metadata") or {},
            "user_id": user_id,
        }
        job = ScheduledJob(
            id=uuid.uuid4().hex,
            user_id=user_id,
            name=str(payload.get("name") or f"{agent_id} schedule"),
            enabled=False,
            schedule_kind=kind,
            delay_seconds=delay,
            interval_seconds=interval,
            timezone=str(payload.get("timezone") or "UTC"),
            run_spec=json.dumps(run_spec, ensure_ascii=False),
            concurrency_policy=str(payload.get("concurrency_policy") or "skip"),
            max_failures=max(1, int(payload.get("max_failures") or 3)),
            next_run_at=next_run,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def list(self, user_id: int) -> list[ScheduledJob]:
        return self.db.query(ScheduledJob).filter(ScheduledJob.user_id == user_id).order_by(ScheduledJob.created_at.desc()).all()

    def owned(self, user_id: int, schedule_id: str) -> ScheduledJob | None:
        return self.db.query(ScheduledJob).filter(ScheduledJob.id == schedule_id, ScheduledJob.user_id == user_id).first()

    def update_draft(self, job: ScheduledJob, payload: dict[str, Any]) -> ScheduledJob:
        if job.enabled:
            raise ValueError("pause schedule before editing")
        if "name" in payload:
            job.name = str(payload["name"] or job.name)
        if "timezone" in payload:
            job.timezone = str(payload["timezone"] or "UTC")
        if "concurrency_policy" in payload:
            job.concurrency_policy = str(payload["concurrency_policy"] or "skip")
        if "max_failures" in payload:
            job.max_failures = max(1, int(payload["max_failures"]))
        if any(key in payload for key in {"input", "session_id", "metadata"}):
            spec = json.loads(job.run_spec or "{}")
            for key in ("input", "session_id", "metadata"):
                if key in payload:
                    spec[key] = payload[key]
            job.run_spec = json.dumps(spec, ensure_ascii=False)
        self.db.commit()
        self.db.refresh(job)
        return job

    def enable(self, job: ScheduledJob, runtime: Any, callback: Callable[[dict[str, Any]], Any]) -> ScheduledJob:
        if job.enabled:
            return job
        spec = json.loads(job.run_spec or "{}")
        if job.schedule_kind == "once":
            remaining = max(1.0, (job.next_run_at - datetime.datetime.utcnow()).total_seconds()) if job.next_run_at else job.delay_seconds or 1.0
            runtime_job_id = runtime.schedule_once(remaining, spec, user_id=job.user_id, callback=callback)
        else:
            runtime_job_id = runtime.schedule_interval(job.interval_seconds or 60.0, spec, user_id=job.user_id, callback=callback)
        job.enabled = True
        job.runtime_job_id = runtime_job_id
        self.db.commit()
        self.db.refresh(job)
        return job

    def pause(self, job: ScheduledJob, runtime: Any) -> ScheduledJob:
        if job.runtime_job_id:
            runtime.cancel_schedule(job.runtime_job_id, user_id=job.user_id)
        job.enabled = False
        job.runtime_job_id = None
        self.db.commit()
        self.db.refresh(job)
        return job

    def delete(self, job: ScheduledJob, runtime: Any) -> None:
        if job.runtime_job_id:
            runtime.cancel_schedule(job.runtime_job_id, user_id=job.user_id)
        self.db.delete(job)
        self.db.commit()

    def record_execution(self, job: ScheduledJob, run_id: str | None, outcome: str, trigger_kind: str = "schedule", error: Exception | None = None) -> ScheduleExecution:
        item = ScheduleExecution(
            id=uuid.uuid4().hex,
            schedule_id=job.id,
            user_id=job.user_id,
            agent_run_id=run_id,
            trigger_kind=trigger_kind,
            outcome=outcome,
            error_code=getattr(error, "code", None) if error else None,
            error_message=str(error) if error else None,
        )
        job.last_run_at = datetime.datetime.utcnow()
        if error is not None:
            job.failure_count += 1
            if job.failure_count >= job.max_failures:
                job.enabled = False
        else:
            job.failure_count = 0
        self.db.add(item)
        self.db.commit()
        return item

    def executions(self, job: ScheduledJob, limit: int = 100) -> list[ScheduleExecution]:
        return self.db.query(ScheduleExecution).filter(ScheduleExecution.schedule_id == job.id).order_by(ScheduleExecution.triggered_at.desc()).limit(limit).all()
