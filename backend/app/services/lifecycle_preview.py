"""Read-only, signed lifecycle preview contracts for future confirmed actions."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import jwt
from core.config import settings
from services.lifecycle_diagnostics import lifecycle_diagnostics
from sqlalchemy.orm import Session

_ALGORITHM = "HS256"
_PURPOSE = "lifecycle_preview_v1"
_ACTIONS = {
    "retention.cleanup",
    "schedule.recovery",
    "plugin.compensation",
    "runtime.shutdown_recovery",
}


def create_lifecycle_preview(
    db: Session,
    *,
    user_id: int,
    retention_days: int,
    action: str = "retention.cleanup",
    target_id: str | None = None,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Create a signed, non-persistent lifecycle preview without mutating state."""
    if action not in _ACTIONS:
        raise ValueError("unsupported lifecycle preview action")
    retention_days = max(1, min(int(retention_days), 3650))
    diagnostics = lifecycle_diagnostics(db, retention_days=retention_days)
    if action == "retention.cleanup":
        candidates = int(diagnostics["retention"]["execution_candidates"])
    elif action == "schedule.recovery":
        candidates = 1 if target_id else int(diagnostics["schedules"]["enabled_counts"].get("false", 0))
    elif action == "plugin.compensation":
        candidates = 1 if target_id else 0
    else:
        runtime = diagnostics.get("runtime") or {}
        candidates = int(runtime.get("active_task_count") or runtime.get("pending_task_count") or 0)
    summary = {
        "action": action,
        "retention_days": retention_days,
        "candidate_count": candidates,
        "target_bound": bool(target_id),
    }
    digest = hashlib.sha256(
        json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    now = dt.datetime.now(dt.timezone.utc)
    expires_at = now + dt.timedelta(seconds=max(60, min(ttl_seconds, 900)))
    claims = {
        "purpose": _PURPOSE,
        "sub": str(user_id),
        "action": action,
        "retention_days": retention_days,
        "candidate_digest": digest,
        "target_digest": hashlib.sha256((target_id or "").encode("utf-8")).hexdigest(),
        "iat": now,
        "exp": expires_at,
    }
    return {
        "read_only": True,
        "action": action,
        "requires_confirm": True,
        "execution_blocked": True,
        "preview_token": jwt.encode(claims, settings.jwt_secret, algorithm=_ALGORITHM),
        "expires_at": expires_at.isoformat(),
        "summary": summary,
        "notice": "Preview only. No retention cleanup, schedule recovery, plugin compensation, or runtime recovery was executed.",
    }


def check_lifecycle_confirmation(
    *,
    token: str,
    user_id: int,
    action: str,
    confirm: bool,
) -> dict[str, Any]:
    """Validate a preview token while explicitly blocking execution in this phase."""
    if not confirm:
        return {
            "confirmation_valid": False,
            "execution_blocked": True,
            "code": "CONFIRM_REQUIRED",
            "message": "Explicit confirmation is required before a future lifecycle action can be considered.",
        }
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return {
            "confirmation_valid": False,
            "execution_blocked": True,
            "code": "PREVIEW_EXPIRED",
            "message": "The lifecycle preview has expired. Generate a new preview.",
        }
    except jwt.PyJWTError:
        return {
            "confirmation_valid": False,
            "execution_blocked": True,
            "code": "PREVIEW_INVALID",
            "message": "The lifecycle preview token is invalid.",
        }
    if claims.get("purpose") != _PURPOSE or claims.get("sub") != str(user_id):
        return {
            "confirmation_valid": False,
            "execution_blocked": True,
            "code": "PREVIEW_SCOPE_MISMATCH",
            "message": "The lifecycle preview does not belong to this administrator.",
        }
    if claims.get("action") != action:
        return {
            "confirmation_valid": False,
            "execution_blocked": True,
            "code": "PREVIEW_ACTION_MISMATCH",
            "message": "The requested lifecycle action does not match the preview.",
        }
    return {
        "confirmation_valid": True,
        "execution_blocked": True,
        "code": "EXECUTION_DISABLED",
        "action": action,
        "candidate_digest": claims.get("candidate_digest"),
        "notice": "Confirmation contract validated. Execution remains disabled until a separately approved lifecycle phase.",
    }
