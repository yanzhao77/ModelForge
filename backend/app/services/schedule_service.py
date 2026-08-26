"""Persistent, user-scoped local schedule definitions and recovery semantics."""
from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from models.records import AgentRun, ScheduleExecution, ScheduledJob
from services.redaction import redact_data, redact_text
from sqlalchemy.orm import Session

_CONCURRENCY = {"skip", "queue_one", "allow_parallel"}
_MISFIRE = {"skip"}
_ACTIVE_RUN_STATES = {"PENDING", "QUEUED", "RUNNING", "WAITING_HUMAN"}


class ScheduleService:
    """Persist conservative schedule definitions and arm only enabled jobs.

    The scheduler remains an in-process timer.  On restart only previously
    enabled definitions are restored, and overdue occurrences are recorded as
    skipped instead of being silently replayed.
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utcnow() -> dt.datetime:
        return dt.datetime.utcnow().replace(tzinfo=None)

    @staticmethod
    def _timezone(value: object) -> ZoneInfo:
        try:
            return ZoneInfo(str(value or "UTC"))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc

    @classmethod
    def _validate(cls, kind: str, delay: float | None, interval: float | None, timezone: object, config: dict[str, Any]) -> None:
        if kind not in {"once", "interval", "daily", "weekly"}:
            raise ValueError("schedule_kind must be once, interval, daily, or weekly")
        cls._timezone(timezone)
        if kind == "once" and (delay is None or delay <= 0):
            raise ValueError("once schedules require a positive delay_seconds")
        if kind == "interval" and (interval is None or interval < 60):
            raise ValueError("interval schedules require interval_seconds >= 60")
        if kind in {"daily", "weekly"}:
            raw_time = str(config.get("time_of_day") or "")
            try:
                hour, minute = (int(value) for value in raw_time.split(":", 1))
            except (TypeError, ValueError) as exc:
                raise ValueError("daily and weekly schedules require time_of_day in HH:MM") from exc
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("time_of_day must be in HH:MM 24-hour format")
        if kind == "weekly" and int(config.get("day_of_week", -1)) not in range(7):
            raise ValueError("weekly schedules require day_of_week from 0 (Monday) to 6 (Sunday)")

    @staticmethod
    def _config(payload: dict[str, Any], prior: dict[str, Any] | None = None) -> dict[str, Any]:
        config = dict(prior or {})
        supplied = payload.get("schedule_config")
        if isinstance(supplied, dict):
            config.update(supplied)
        for key in ("time_of_day", "day_of_week"):
            if key in payload:
                config[key] = payload[key]
        return config

    @classmethod
    def _next_run(cls, job: ScheduledJob, *, after: dt.datetime | None = None) -> dt.datetime | None:
        after = after or cls._utcnow()
        if job.schedule_kind == "once":
            return after + dt.timedelta(seconds=job.delay_seconds or 1)
        if job.schedule_kind == "interval":
            return after + dt.timedelta(seconds=job.interval_seconds or 60)
        config = json.loads(job.schedule_config or "{}")
        hour, minute = (int(value) for value in str(config["time_of_day"]).split(":", 1))
        zone = cls._timezone(job.timezone)
        local_after = after.replace(tzinfo=dt.timezone.utc).astimezone(zone)
        candidate = local_after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if job.schedule_kind == "weekly":
            candidate += dt.timedelta(days=(int(config["day_of_week"]) - candidate.weekday()) % 7)
        if candidate <= local_after:
            candidate += dt.timedelta(days=7 if job.schedule_kind == "weekly" else 1)
        return candidate.astimezone(dt.timezone.utc).replace(tzinfo=None)

    def _validate_payload(self, payload: dict[str, Any], *, prior_config: dict[str, Any] | None = None) -> tuple[str, float | None, float | None, str, dict[str, Any], str, str]:
        kind = str(payload.get("schedule_kind") or payload.get("type") or "")
        delay = payload.get("delay_seconds")
        interval = payload.get("interval_seconds")
        delay = float(delay) if delay is not None else None
        interval = float(interval) if interval is not None else None
        timezone = str(payload.get("timezone") or "UTC")
        config = self._config(payload, prior_config)
        concurrency = str(payload.get("concurrency_policy") or "skip")
        misfire = str(payload.get("misfire_policy") or "skip")
        self._validate(kind, delay, interval, timezone, config)
        if concurrency not in _CONCURRENCY:
            raise ValueError("concurrency_policy must be skip, queue_one, or allow_parallel")
        if misfire not in _MISFIRE:
            raise ValueError("misfire_policy must be skip")
        return kind, delay, interval, timezone, config, concurrency, misfire

    def create_draft(self, user_id: int, payload: dict[str, Any]) -> ScheduledJob:
        kind, delay, interval, timezone, config, concurrency, misfire = self._validate_payload(payload)
        agent_id = str(payload.get("agent_id") or "")
        if not agent_id:
            raise ValueError("agent_id required")
        run_spec = {
            "agent_id": agent_id,
            "input": str(payload.get("input") or ""),
            "session_id": payload.get("session_id"),
            "metadata": redact_data(payload.get("metadata") or {}),
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
            timezone=timezone,
            schedule_config=json.dumps(config, ensure_ascii=False),
            misfire_policy=misfire,
            run_spec=json.dumps(run_spec, ensure_ascii=False),
            concurrency_policy=concurrency,
            max_failures=max(1, int(payload.get("max_failures") or 3)),
        )
        job.next_run_at = self._next_run(job)
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
        prior_config = json.loads(job.schedule_config or "{}")
        merged = {
            "schedule_kind": payload.get("schedule_kind", job.schedule_kind),
            "delay_seconds": payload.get("delay_seconds", job.delay_seconds),
            "interval_seconds": payload.get("interval_seconds", job.interval_seconds),
            "timezone": payload.get("timezone", job.timezone),
            "concurrency_policy": payload.get("concurrency_policy", job.concurrency_policy),
            "misfire_policy": payload.get("misfire_policy", job.misfire_policy),
            **payload,
        }
        kind, delay, interval, timezone, config, concurrency, misfire = self._validate_payload(merged, prior_config=prior_config)
        job.schedule_kind = kind
        job.delay_seconds = delay
        job.interval_seconds = interval
        job.timezone = timezone
        job.schedule_config = json.dumps(config, ensure_ascii=False)
        job.concurrency_policy = concurrency
        job.misfire_policy = misfire
        if "name" in payload:
            job.name = str(payload["name"] or job.name)
        if "max_failures" in payload:
            job.max_failures = max(1, int(payload["max_failures"]))
        if any(key in payload for key in {"input", "session_id", "metadata"}):
            spec = json.loads(job.run_spec or "{}")
            for key in ("input", "session_id", "metadata"):
                if key in payload:
                    spec[key] = payload[key]
            job.run_spec = json.dumps(spec, ensure_ascii=False)
        job.next_run_at = self._next_run(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def preview(self, job: ScheduledJob, count: int = 5) -> list[str]:
        if job.schedule_kind == "once":
            return [job.next_run_at.isoformat()] if job.next_run_at else []
        result: list[str] = []
        cursor = job.next_run_at or self._next_run(job)
        for _ in range(max(1, min(count, 10))):
            if cursor is None:
                break
            result.append(cursor.isoformat())
            cursor = self._next_run(job, after=cursor)
        return result

    @staticmethod
    def _callback(callback_factory: Callable[[str], Callable[[dict[str, Any]], Any]], job: ScheduledJob) -> Callable[[dict[str, Any]], Any]:
        return callback_factory(job.id)

    def _arm(self, job: ScheduledJob, runtime: Any, callback_factory: Callable[[str], Callable[[dict[str, Any]], Any]]) -> None:
        if not job.enabled or job.next_run_at is None:
            job.runtime_job_id = None
            return
        delay = max(1.0, (job.next_run_at - self._utcnow()).total_seconds())
        job.runtime_job_id = runtime.schedule_once(delay, json.loads(job.run_spec or "{}"), user_id=job.user_id, callback=self._callback(callback_factory, job))

    def enable(self, job: ScheduledJob, runtime: Any, callback_factory: Callable[[str], Callable[[dict[str, Any]], Any]]) -> ScheduledJob:
        if job.enabled:
            return job
        now = self._utcnow()
        job.enabled = True
        job.pending_trigger = False
        if job.next_run_at is None or job.next_run_at <= now:
            job.next_run_at = self._next_run(job, after=now)
        self._arm(job, runtime, callback_factory)
        self.db.commit()
        self.db.refresh(job)
        return job

    def pause(self, job: ScheduledJob, runtime: Any) -> ScheduledJob:
        if job.runtime_job_id:
            runtime.cancel_schedule(job.runtime_job_id, user_id=job.user_id)
        job.enabled = False
        job.runtime_job_id = None
        job.pending_trigger = False
        self.db.commit()
        self.db.refresh(job)
        return job

    def delete(self, job: ScheduledJob, runtime: Any) -> None:
        if job.runtime_job_id:
            runtime.cancel_schedule(job.runtime_job_id, user_id=job.user_id)
        self.db.delete(job)
        self.db.commit()

    def _append_execution(self, job: ScheduledJob, outcome: str, *, trigger_kind: str = "schedule", run_id: str | None = None, error: Exception | None = None) -> ScheduleExecution:
        item = ScheduleExecution(
            id=uuid.uuid4().hex,
            schedule_id=job.id,
            user_id=job.user_id,
            agent_run_id=run_id,
            trigger_kind=trigger_kind,
            outcome=outcome,
            error_code=getattr(error, "code", None) if error else None,
            error_message=redact_text(error) if error else None,
        )
        self.db.add(item)
        return item

    def active_run_count(self, job: ScheduledJob) -> int:
        return (
            self.db.query(ScheduleExecution)
            .join(AgentRun, AgentRun.run_id == ScheduleExecution.agent_run_id)
            .filter(ScheduleExecution.schedule_id == job.id, AgentRun.status.in_(_ACTIVE_RUN_STATES))
            .count()
        )

    def claim_trigger(self, job: ScheduledJob, *, trigger_kind: str = "schedule") -> str:
        """Claim a scheduler callback without creating an Agent Run itself."""
        if not job.enabled:
            return "disabled"
        active = self.active_run_count(job)
        if active and job.concurrency_policy == "skip":
            self._append_execution(job, "skipped_concurrency", trigger_kind=trigger_kind)
            self.db.commit()
            return "skipped"
        if active and job.concurrency_policy == "queue_one":
            if job.pending_trigger:
                self._append_execution(job, "skipped_concurrency", trigger_kind=trigger_kind)
                self.db.commit()
                return "pending"
            job.pending_trigger = True
            self._append_execution(job, "queued", trigger_kind=trigger_kind)
            self.db.commit()
            return "queued"
        job.pending_trigger = False
        self.db.commit()
        return "run"

    def defer_pending(self, job: ScheduledJob, runtime: Any, callback_factory: Callable[[str], Callable[[dict[str, Any]], Any]], seconds: float = 5.0) -> None:
        """Schedule a bounded in-memory recheck for the one permitted pending trigger.

        The recheck is intentionally not persisted as a second definition: a
        pause/delete still makes the callback a no-op through ``claim_trigger``.
        """
        spec = {**json.loads(job.run_spec or "{}"), "_schedule_queue_recheck": True}
        runtime.schedule_once(max(1.0, seconds), spec, user_id=job.user_id, callback=self._callback(callback_factory, job))

    def advance_after_callback(self, job: ScheduledJob, runtime: Any, callback_factory: Callable[[str], Callable[[dict[str, Any]], Any]]) -> None:
        """Advance a durable occurrence before attempting its associated Run."""
        now = self._utcnow()
        job.last_run_at = now
        if job.schedule_kind == "once":
            job.enabled = False
            job.runtime_job_id = None
            job.next_run_at = None
        else:
            job.next_run_at = self._next_run(job, after=now)
            self._arm(job, runtime, callback_factory)
        self.db.commit()

    def record_execution(self, job: ScheduledJob, run_id: str | None, outcome: str, trigger_kind: str = "schedule", error: Exception | None = None) -> ScheduleExecution:
        item = self._append_execution(job, outcome, trigger_kind=trigger_kind, run_id=run_id, error=error)
        if error is not None:
            job.failure_count += 1
            if job.failure_count >= job.max_failures:
                job.enabled = False
                job.runtime_job_id = None
        elif outcome == "triggered":
            job.failure_count = 0
        self.db.commit()
        return item

    def restore_enabled(self, runtime: Any, callback_factory: Callable[[str], Callable[[dict[str, Any]], Any]]) -> int:
        """Restore only explicitly enabled jobs; overdue occurrences are skipped."""
        now = self._utcnow()
        restored = 0
        for job in self.db.query(ScheduledJob).filter(ScheduledJob.enabled.is_(True)).all():
            job.runtime_job_id = None
            if job.next_run_at is None or job.next_run_at <= now:
                self._append_execution(job, "skipped_misfire", trigger_kind="recovery")
                if job.schedule_kind == "once":
                    job.enabled = False
                    job.next_run_at = None
                else:
                    job.next_run_at = self._next_run(job, after=now)
            if job.enabled:
                self._arm(job, runtime, callback_factory)
                restored += 1
        self.db.commit()
        return restored

    def executions(self, job: ScheduledJob, limit: int = 100) -> list[ScheduleExecution]:
        return self.db.query(ScheduleExecution).filter(ScheduleExecution.schedule_id == job.id).order_by(ScheduleExecution.triggered_at.desc()).limit(limit).all()
