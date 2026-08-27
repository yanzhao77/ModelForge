"""Content-free control-plane budget summaries."""
from __future__ import annotations

from typing import Any

from core.config import settings


def _budget(limit: float | None, used: float) -> dict[str, Any]:
    safe_limit = None if limit is None else max(0.0, float(limit))
    safe_used = max(0.0, float(used))
    return {
        "limit": safe_limit,
        "used": round(safe_used, 8),
        "remaining": None if safe_limit is None else round(max(0.0, safe_limit - safe_used), 8),
        "status": "not_configured" if safe_limit is None else ("exceeded" if safe_used >= safe_limit else "within_limit"),
        "reason_code": None if safe_limit is not None else "BUDGET_NOT_CONFIGURED",
    }


def control_plane_budget_summary(
    *,
    daily_budget: float | None,
    weekly_budget: float | None,
    daily_used: float,
    weekly_used: float,
    active_task_count: int,
) -> dict[str, Any]:
    """Return configured ceilings and aggregate usage without accessing runtime work."""
    runtime = settings.runtime
    return {
        "read_only": True,
        "enforcement": "informational_only",
        "budgets": {
            "daily": _budget(daily_budget, daily_used),
            "weekly": _budget(weekly_budget, weekly_used),
        },
        "queue": {
            "active_count": max(0, int(active_task_count)),
            "limit": None,
            "remaining": None,
            "status": "not_configured",
            "reason_code": "QUEUE_LIMIT_NOT_CONFIGURED",
        },
        "delegation": {
            "max_depth": 3,
            "max_children": 5,
            "status": "configured_default",
            "reason_code": None,
        },
        "tool_policy": {
            "max_iterations": int(runtime.max_iterations),
            "max_tool_calls": int(runtime.max_tool_calls),
            "status": "configured_default",
            "reason_code": None,
        },
        "notice": "Informational summary only. It never starts, routes, stops, or changes an Agent Run, tool call, provider request, queue item, or delegation.",
    }
