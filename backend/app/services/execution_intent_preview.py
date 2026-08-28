"""Read-only signed summaries for future high-risk control-plane confirmations.

The service deliberately only hashes caller-supplied identifiers.  It never
resolves a target, persists an intent, writes audit data, or executes work.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import jwt
from core.action_risk import action_risk
from core.config import settings

_ALGORITHM = "HS256"
_PURPOSE = "execution_intent_preview_v2"
_SUMMARY_SCHEMA_VERSION = 2
_MAX_TARGETS = 50
_MAX_TARGET_ID_LENGTH = 160


def _digest(value: Any) -> str:
    """Return a stable digest without retaining its source value."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_targets(target_ids: list[str]) -> list[str]:
    """Canonicalize identifiers without resolving or exposing them."""
    safe: set[str] = set()
    for raw_value in target_ids:
        value = str(raw_value)
        if not value or len(value) > _MAX_TARGET_ID_LENGTH:
            raise ValueError("invalid preview target")
        safe.add(value)
    targets = sorted(safe)
    if not targets or len(targets) > _MAX_TARGETS:
        raise ValueError("invalid preview target count")
    return targets


def _safe_version_bindings(
    targets: list[str],
    expected_versions_by_target: dict[str, int] | None,
    legacy_expected_versions: list[int] | None,
) -> tuple[list[dict[str, int | None]], str, bool, int, str]:
    """Hash per-target versions while retaining legacy input only as a summary.

    A legacy positional list cannot safely bind a version to a target.  It is
    kept only for request compatibility and is explicitly reported as unbound.
    """
    legacy_values: list[int] = []
    for value in legacy_expected_versions or []:
        normalized = int(value)
        if normalized < 0:
            raise ValueError("invalid expected version")
        legacy_values.append(normalized)
    if len(legacy_values) > _MAX_TARGETS:
        raise ValueError("too many expected versions")

    raw_supplied = expected_versions_by_target or {}
    if len(raw_supplied) > _MAX_TARGETS:
        raise ValueError("too many target version bindings")
    supplied: dict[str, int] = {}
    for raw_target, raw_version in raw_supplied.items():
        target = str(raw_target)
        if not target or len(target) > _MAX_TARGET_ID_LENGTH:
            raise ValueError("invalid target version binding")
        supplied[target] = raw_version
    unknown_targets = set(supplied) - set(targets)
    if unknown_targets:
        raise ValueError("target version binding is out of scope")

    bindings: list[dict[str, int | None]] = []
    for target in targets:
        raw_version = supplied.get(target)
        if raw_version is None:
            bindings.append({"target": target, "expected_version": None})
            continue
        normalized = int(raw_version)
        if normalized < 0:
            raise ValueError("invalid expected version")
        bindings.append({"target": target, "expected_version": normalized})

    binding_complete = bool(supplied) and all(item["expected_version"] is not None for item in bindings)
    legacy_digest = _digest(legacy_values)
    return bindings, _digest(bindings), binding_complete, len(legacy_values), legacy_digest


def create_execution_intent_preview(
    *,
    user_id: int,
    action: str,
    target_ids: list[str],
    expected_versions: list[int] | None = None,
    expected_versions_by_target: dict[str, int] | None = None,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Create a non-persistent summary without resolving targets or executing work."""
    risk = action_risk(action)
    if risk is None or not risk.requires_confirmation:
        raise ValueError("unsupported execution-intent preview action")
    targets = _safe_targets(target_ids)
    bindings, binding_digest, binding_complete, legacy_count, legacy_digest = _safe_version_bindings(
        targets,
        expected_versions_by_target,
        expected_versions,
    )
    summary = {
        "schema_version": _SUMMARY_SCHEMA_VERSION,
        "action": action,
        "risk_tier": risk.tier,
        "object_type": risk.object_type,
        "target_count": len(targets),
        "target_digest": _digest(targets),
        "target_version_binding_digest": binding_digest,
        "target_version_binding_complete": binding_complete,
        "legacy_expected_version_count": legacy_count,
        "legacy_expected_version_digest": legacy_digest,
    }
    now = dt.datetime.now(dt.timezone.utc)
    expires_at = now + dt.timedelta(seconds=max(60, min(ttl_seconds, 900)))
    claims = {
        "purpose": _PURPOSE,
        "schema_version": _SUMMARY_SCHEMA_VERSION,
        "sub": str(user_id),
        "action": action,
        "risk_tier": risk.tier,
        "object_type": risk.object_type,
        "target_digest": summary["target_digest"],
        "target_version_binding_digest": binding_digest,
        "target_version_binding_complete": binding_complete,
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
        return {"confirmation_valid": False, "execution_blocked": True, "code": "EXECUTION_INTENT_CONFIRMATION_REQUIRED"}
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "EXECUTION_INTENT_PREVIEW_EXPIRED"}
    except jwt.PyJWTError:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "EXECUTION_INTENT_PREVIEW_INVALID"}
    if claims.get("purpose") != _PURPOSE or claims.get("schema_version") != _SUMMARY_SCHEMA_VERSION:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "EXECUTION_INTENT_PREVIEW_SCHEMA_MISMATCH"}
    if claims.get("sub") != str(user_id):
        return {"confirmation_valid": False, "execution_blocked": True, "code": "EXECUTION_INTENT_PREVIEW_SCOPE_MISMATCH"}
    if claims.get("action") != action:
        return {"confirmation_valid": False, "execution_blocked": True, "code": "EXECUTION_INTENT_PREVIEW_ACTION_MISMATCH"}
    return {
        "confirmation_valid": True,
        "execution_blocked": True,
        "code": "EXECUTION_INTENT_EXECUTION_DISABLED",
        "summary": {
            "schema_version": claims.get("schema_version"),
            "action": action,
            "risk_tier": claims.get("risk_tier"),
            "object_type": claims.get("object_type"),
            "target_count": claims.get("target_count"),
            "target_digest": claims.get("target_digest"),
            "target_version_binding_digest": claims.get("target_version_binding_digest"),
            "target_version_binding_complete": bool(claims.get("target_version_binding_complete")),
        },
        "notice": "Confirmation contract validated. Execution remains disabled until a separately approved phase.",
    }
