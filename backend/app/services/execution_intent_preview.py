"""Read-only, signed summaries for future high-risk control-plane confirmations."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import jwt
from core.action_risk import action_risk
from core.config import settings


_ALGORITHM = "HS256"
_PURPOSE = "execution_intent_preview_v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def create_execution_intent_preview(
    *,
    user_id: int,
    action: str,
    target_ids: list[str],
    expected_versions: list[int] | None = None,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Create a non-persistent preview without resolving targets or executing work."""
    risk = action_risk(action)
    if risk is None or not risk.requires_confirmation:
        raise ValueError("unsupported execution-intent preview action")
    safe_targets = sorted({str(value)[:160] for value in target_ids if str(value)})[:50]
    safe_versions = [max(0, int(value)) for value in (expected_versions or [])][:50]
    summary = {
        "action": action,
        "risk_tier": risk.tier,
        "object_type": risk.object_type,
        "target_count": len(safe_targets),
        "target_digest": _digest(safe_targets),
        "expected_version_count": len(safe_versions),
        "expected_version_digest": _digest(safe_versions),
    }
    now = dt.datetime.now(dt.timezone.utc)
    expires_at = now + dt.timedelta(seconds=max(60, min(ttl_seconds, 900)))
    claims = {
        "purpose": _PURPOSE,
        "sub": str(user_id),
        "action": action,
        "target_digest": summary["target_digest"],
        "expected_version_digest": summary["expected_version_digest"],
        "target_count": summary["target_count"],
        "iat": now,
        "exp": expires_at,
    }
    return {
        "read_only": True,
        "execution_blocked": True,
        "requires_confirm": True,
        "preview_token": jwt.encode(claims, settings.jwt_secret, algorithm=_ALGORITHM),
        "expires_at": expires_at.isoformat(),
        "summary": summary,
        "notice": "Preview only. No target lookup, audit write, runtime call, task action, training action, provider call, or plugin action was performed.",
    }


def check_execution_intent_preview(
    *,
    token: str,
    user_id: int,
    action: str,
    confirm: bool,
) -> dict[str, Any]:
    """Validate a preview token while keeping all execution paths explicitly blocked."""
    if not confirm:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "CONFIRM_REQUIRED"}
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "PREVIEW_EXPIRED"}
    except jwt.PyJWTError:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "PREVIEW_INVALID"}
    if claims.get("purpose") != _PURPOSE or claims.get("sub") != str(user_id):
        return {"confirmation_valid": False, "execution_blocked": True, "code": "PREVIEW_SCOPE_MISMATCH"}
    if claims.get("action") != action:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "PREVIEW_ACTION_MISMATCH"}
    return {
        "confirmation_valid": True,
        "execution_blocked": True,
        "code": "EXECUTION_DISABLED",
        "action": action,
        "target_count": claims.get("target_count"),
        "target_digest": claims.get("target_digest"),
        "notice": "Confirmation contract validated. Execution remains disabled until a separately approved phase.",
    }
