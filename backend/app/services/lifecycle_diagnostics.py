"""Read-only lifecycle and retention diagnostics for runtime operators."""
from __future__ import annotations

import datetime as dt
from typing import Any

from models.records import ScheduleExecution, ScheduledJob
from sqlalchemy import func
from sqlalchemy.orm import Session


def lifecycle_diagnostics(db: Session, retention_days: int = 30) -> dict[str, Any]:
    """Summarize lifecycle ownership and retention candidates without mutation."""
    from services.agent_runtime_service import get_agent_runtime

    now = dt.datetime.utcnow()
    cutoff = now - dt.timedelta(days=max(1, min(retention_days, 3650)))
    runtime = get_agent_runtime()
    snapshot = getattr(runtime, "lifecycle_snapshot", None) if runtime is not None else None
    schedule_statuses = {
        str(enabled).lower(): int(count)
        for enabled, count in db.query(ScheduledJob.enabled, func.count(ScheduledJob.id)).group_by(ScheduledJob.enabled).all()
    }
    return {
        "read_only": True,
        "diagnostic_time": now.isoformat(),
        "notice": "This view does not stop the runtime, recover schedules, enable jobs, or delete retained records.",
        "runtime": snapshot() if callable(snapshot) else {"available": False},
        "schedules": {
            "enabled_counts": schedule_statuses,
            "pending_trigger_count": db.query(ScheduledJob).filter(ScheduledJob.pending_trigger.is_(True)).count(),
            "next_24h_count": db.query(ScheduledJob).filter(ScheduledJob.enabled.is_(True), ScheduledJob.next_run_at.isnot(None), ScheduledJob.next_run_at <= now + dt.timedelta(hours=24)).count(),
        },
        "retention": {
            "policy_days": retention_days,
            "execution_candidates": db.query(ScheduleExecution)
            .filter(ScheduleExecution.finished_at.isnot(None), ScheduleExecution.finished_at < cutoff)
            .count(),
            "action": "manual_review_required",
        },
    }
