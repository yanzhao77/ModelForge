"""Read-only, content-free diagnostics for concurrency and event delivery."""
from __future__ import annotations

import datetime as dt
from typing import Any

from models.records import AgentEventRecord, AgentRun, ScheduleExecution, TaskOutbox
from sqlalchemy import func
from sqlalchemy.orm import Session


def _counts(query, key_column) -> dict[str, int]:
    return {str(key or "unknown"): int(count) for key, count in query.group_by(key_column).all()}


def runtime_diagnostics(db: Session) -> dict[str, Any]:
    """Return aggregate persistence health without reading payloads or output."""
    from services.agent_runtime_service import get_agent_runtime

    now = dt.datetime.utcnow()
    runtime = get_agent_runtime()
    snapshot = getattr(runtime, "lifecycle_snapshot", None) if runtime is not None else None
    runtime_health = snapshot() if callable(snapshot) else {}
    # Keep diagnostics aligned with the RunStatus values persisted by the runtime.
    active_states = ("PENDING", "RUNNING", "WAITING_HUMAN")
    run_statuses = _counts(db.query(AgentRun.status, func.count(AgentRun.run_id)), AgentRun.status)
    execution_outcomes = _counts(
        db.query(ScheduleExecution.outcome, func.count(ScheduleExecution.id)),
        ScheduleExecution.outcome,
    )
    duplicate_event_keys = (
        db.query(AgentEventRecord.run_id, AgentEventRecord.event_key)
        .filter(AgentEventRecord.event_key.isnot(None))
        .group_by(AgentEventRecord.run_id, AgentEventRecord.event_key)
        .having(func.count(AgentEventRecord.id) > 1)
        .count()
    )
    outbox_pending = db.query(TaskOutbox).filter(TaskOutbox.dispatched_at.is_(None))
    return {
        "read_only": True,
        "diagnostic_time": now.isoformat(),
        "notice": "Aggregate diagnostics only. No Run, schedule, event, outbox, or lease was changed.",
        "runs": {
            "status_counts": run_statuses,
            "active_count": db.query(AgentRun).filter(AgentRun.status.in_(active_states)).count(),
            "leased_count": db.query(AgentRun).filter(AgentRun.executor_lease_id.isnot(None)).count(),
            "expired_lease_count": db.query(AgentRun)
            .filter(AgentRun.executor_lease_id.isnot(None), AgentRun.lease_expires_at.isnot(None), AgentRun.lease_expires_at < now)
            .count(),
        },
        "schedule_claims": {
            "outcome_counts": execution_outcomes,
            "active_claim_count": db.query(ScheduleExecution)
            .filter(ScheduleExecution.claim_token.isnot(None), ScheduleExecution.claim_expires_at.isnot(None), ScheduleExecution.claim_expires_at >= now)
            .count(),
            "expired_claim_count": db.query(ScheduleExecution)
            .filter(ScheduleExecution.claim_token.isnot(None), ScheduleExecution.claim_expires_at.isnot(None), ScheduleExecution.claim_expires_at < now)
            .count(),
        },
        "events": {
            "total_count": db.query(AgentEventRecord).count(),
            "keyed_count": db.query(AgentEventRecord).filter(AgentEventRecord.event_key.isnot(None)).count(),
            "missing_key_count": db.query(AgentEventRecord).filter(AgentEventRecord.event_key.is_(None)).count(),
            "duplicate_key_group_count": duplicate_event_keys,
            "event_bus": runtime_health.get("event_bus") or {"available": False},
        },
        "background_tasks": runtime_health.get("background_tasks") or {"tracked_count": 0, "failure_count": 0, "spawn_rejection_count": 0, "last_failure_type": None},
        "task_outbox": {
            "pending_count": outbox_pending.count(),
            "active_lease_count": outbox_pending.filter(TaskOutbox.lease_token.isnot(None), TaskOutbox.lease_expires_at.isnot(None), TaskOutbox.lease_expires_at >= now).count(),
            "expired_lease_count": outbox_pending.filter(TaskOutbox.lease_token.isnot(None), TaskOutbox.lease_expires_at.isnot(None), TaskOutbox.lease_expires_at < now).count(),
            "retry_due_count": outbox_pending.filter(TaskOutbox.next_attempt_at.isnot(None), TaskOutbox.next_attempt_at <= now).count(),
            "max_attempts": int(db.query(func.coalesce(func.max(TaskOutbox.attempts), 0)).scalar() or 0),
        },
    }
