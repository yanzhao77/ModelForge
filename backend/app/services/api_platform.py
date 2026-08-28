"""Project-scoped commercial API control-plane primitives.

The service deliberately keeps API-key issuance, idempotency, quota reservation,
and immutable usage recording in the same database transaction boundaries. It is
not a payment processor: its ledger is an auditable source for later invoicing.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass

from core.config import settings
from models.records import (
    AgentRecord,
    ApiInvocation,
    ApiProject,
    Organization,
    ProjectAgentBinding,
    ProjectApiKey,
    ProjectQuota,
    UsageLedger,
    User,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

DEFAULT_SCOPES = {"agent:run", "usage:read"}
_ACTIVE_INVOCATION_STATUSES = {"PENDING", "RUNNING"}


class PlatformError(ValueError):
    """A safe, stable error produced by the commercial API control plane."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(code)


@dataclass(frozen=True)
class ApiPrincipal:
    key_id: str
    project_id: str
    user_id: int
    scopes: frozenset[str]


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def _id() -> str:
    return uuid.uuid4().hex


def _key_hash(raw_key: str) -> str:
    # A keyed, one-way MAC prevents a database leak from becoming an offline
    # plaintext API-key oracle while retaining constant-time verification.
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), raw_key.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _canonical_request_hash(agent_id: str, input_text: str, max_tokens: int) -> str:
    payload = json.dumps(
        {"agent_id": agent_id, "input": input_text, "max_tokens": max_tokens},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_organization(db: Session, owner: User, name: str) -> Organization:
    normalized = name.strip()
    if not normalized:
        raise PlatformError("ORGANIZATION_NAME_REQUIRED", "Organization name is required.")
    duplicate = db.query(Organization).filter_by(owner_user_id=owner.id, name=normalized).first()
    if duplicate is not None:
        raise PlatformError("ORGANIZATION_NAME_CONFLICT", "Organization name is already in use.")
    organization = Organization(id=_id(), owner_user_id=owner.id, name=normalized)
    db.add(organization)
    db.flush()
    return organization


def get_owned_organization(db: Session, organization_id: str, owner_id: int) -> Organization:
    organization = db.query(Organization).filter_by(id=organization_id, owner_user_id=owner_id).first()
    if organization is None or organization.status != "active":
        raise PlatformError("ORGANIZATION_NOT_FOUND", "Organization was not found.")
    return organization


def create_project(db: Session, organization: Organization, owner: User, name: str, environment: str) -> ApiProject:
    normalized = name.strip()
    if not normalized:
        raise PlatformError("PROJECT_NAME_REQUIRED", "Project name is required.")
    if environment not in {"test", "live"}:
        raise PlatformError("PROJECT_ENVIRONMENT_INVALID", "Project environment must be test or live.")
    duplicate = db.query(ApiProject).filter_by(organization_id=organization.id, name=normalized).first()
    if duplicate is not None:
        raise PlatformError("PROJECT_NAME_CONFLICT", "Project name is already in use.")
    project = ApiProject(
        id=_id(), organization_id=organization.id, owner_user_id=owner.id,
        name=normalized, environment=environment,
    )
    db.add(project)
    db.add(ProjectQuota(project_id=project.id, updated_by_user_id=owner.id))
    db.flush()
    return project


def get_owned_project(db: Session, project_id: str, owner_id: int) -> ApiProject:
    project = db.query(ApiProject).filter_by(id=project_id, owner_user_id=owner_id).first()
    if project is None or project.status != "active":
        raise PlatformError("PROJECT_NOT_FOUND", "Project was not found.")
    return project


def bind_project_agent(db: Session, project: ApiProject, owner: User, agent_id: str) -> ProjectAgentBinding:
    """Allow a project to invoke a specific Agent owned by its customer account."""
    agent = db.query(AgentRecord).filter_by(name=agent_id, user_id=owner.id).first()
    if agent is None:
        raise PlatformError("AGENT_NOT_FOUND", "Agent was not found.")
    binding = db.query(ProjectAgentBinding).filter_by(project_id=project.id, agent_id=agent_id).first()
    if binding is None:
        binding = ProjectAgentBinding(id=_id(), project_id=project.id, agent_id=agent_id, user_id=owner.id)
        db.add(binding)
        db.flush()
    return binding


def is_project_agent_bound(db: Session, project_id: str, user_id: int, agent_id: str) -> bool:
    return db.query(ProjectAgentBinding).filter_by(project_id=project_id, user_id=user_id, agent_id=agent_id).first() is not None


def issue_project_key(db: Session, project: ApiProject, owner: User, name: str, scopes: list[str], expires_at: dt.datetime | None = None) -> tuple[ProjectApiKey, str]:
    effective_scopes = {scope.strip() for scope in (scopes or list(DEFAULT_SCOPES)) if scope.strip()}
    if not effective_scopes or not effective_scopes.issubset(DEFAULT_SCOPES):
        raise PlatformError("API_KEY_SCOPE_INVALID", "One or more API key scopes are invalid.")
    if expires_at is not None and expires_at <= _now():
        raise PlatformError("API_KEY_EXPIRY_INVALID", "API key expiry must be in the future.")
    prefix = "mf_" + secrets.token_hex(6)
    # Hex avoids delimiter ambiguity; the prefix remains a non-secret lookup key.
    secret = secrets.token_hex(32)
    raw_key = f"{prefix}_{secret}"
    key = ProjectApiKey(
        id=_id(), project_id=project.id, created_by_user_id=owner.id, name=name.strip() or "default",
        prefix=prefix, secret_hash=_key_hash(raw_key), scopes_json=json.dumps(sorted(effective_scopes)),
        expires_at=expires_at,
    )
    db.add(key)
    db.flush()
    return key, raw_key


def revoke_project_key(db: Session, key_id: str, project: ApiProject) -> ProjectApiKey:
    key = db.query(ProjectApiKey).filter_by(id=key_id, project_id=project.id).first()
    if key is None:
        raise PlatformError("API_KEY_NOT_FOUND", "API key was not found.")
    if key.revoked_at is None:
        key.revoked_at = _now()
        db.flush()
    return key


def authenticate_project_key(db: Session, raw_key: str | None, required_scope: str) -> ApiPrincipal:
    # Prefix has a fixed ``mf_`` + 12 hexadecimal-character format. Parse by
    # fixed width instead of splitting the secret, so existing URL-safe secrets
    # containing underscores remain valid.
    if not raw_key or len(raw_key) <= 16 or not raw_key.startswith("mf_") or raw_key[15] != "_":
        raise PlatformError("API_KEY_INVALID", "API key is invalid.")
    prefix = raw_key[:15]
    key = db.query(ProjectApiKey).filter_by(prefix=prefix).first()
    if key is None or key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= _now()):
        raise PlatformError("API_KEY_INVALID", "API key is invalid or expired.")
    if not hmac.compare_digest(key.secret_hash, _key_hash(raw_key)):
        raise PlatformError("API_KEY_INVALID", "API key is invalid.")
    project = db.query(ApiProject).filter_by(id=key.project_id).first()
    if project is None or project.status != "active":
        raise PlatformError("PROJECT_NOT_FOUND", "Project was not found.")
    scopes = frozenset(json.loads(key.scopes_json or "[]"))
    if required_scope not in scopes:
        raise PlatformError("API_KEY_SCOPE_DENIED", "API key does not grant this operation.")
    key.last_used_at = _now()
    db.flush()
    return ApiPrincipal(key_id=key.id, project_id=project.id, user_id=project.owner_user_id, scopes=scopes)


def get_quota(db: Session, project_id: str) -> ProjectQuota:
    quota = db.query(ProjectQuota).filter_by(project_id=project_id).first()
    if quota is None:
        quota = ProjectQuota(project_id=project_id)
        db.add(quota)
        db.flush()
    return quota


def update_quota(db: Session, project: ApiProject, owner: User, *, max_concurrent_runs: int, daily_token_limit: int, monthly_token_limit: int, per_run_token_limit: int) -> ProjectQuota:
    values = (max_concurrent_runs, daily_token_limit, monthly_token_limit, per_run_token_limit)
    if any(value < 1 for value in values) or per_run_token_limit > daily_token_limit or daily_token_limit > monthly_token_limit:
        raise PlatformError("QUOTA_CONFIGURATION_INVALID", "Quota limits are inconsistent.")
    quota = get_quota(db, project.id)
    quota.max_concurrent_runs = max_concurrent_runs
    quota.daily_token_limit = daily_token_limit
    quota.monthly_token_limit = monthly_token_limit
    quota.per_run_token_limit = per_run_token_limit
    quota.updated_by_user_id = owner.id
    db.flush()
    return quota


def _usage_total(db: Session, project_id: str, since: dt.datetime) -> int:
    return int(
        db.query(func.coalesce(func.sum(UsageLedger.quantity), 0))
        .filter(UsageLedger.project_id == project_id, UsageLedger.metric_type == "tokens", UsageLedger.occurred_at >= since)
        .scalar()
        or 0
    )


def _reserved_total(db: Session, project_id: str, since: dt.datetime) -> int:
    return int(
        db.query(func.coalesce(func.sum(ApiInvocation.reserved_tokens), 0))
        .filter(ApiInvocation.project_id == project_id, ApiInvocation.status.in_(_ACTIVE_INVOCATION_STATUSES), ApiInvocation.created_at >= since)
        .scalar()
        or 0
    )


def prepare_invocation(db: Session, principal: ApiPrincipal, *, idempotency_key: str, request_hash: str, agent_id: str, requested_tokens: int) -> tuple[ApiInvocation, bool]:
    if not idempotency_key or len(idempotency_key) > 128:
        raise PlatformError("IDEMPOTENCY_KEY_REQUIRED", "A bounded Idempotency-Key header is required.")
    existing = db.query(ApiInvocation).filter_by(project_id=principal.project_id, idempotency_key=idempotency_key).first()
    if existing is not None:
        if not hmac.compare_digest(existing.request_hash, request_hash):
            raise PlatformError("IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used for a different request.")
        return existing, True
    quota = get_quota(db, principal.project_id)
    if requested_tokens < 1 or requested_tokens > quota.per_run_token_limit:
        raise PlatformError("PER_RUN_QUOTA_EXCEEDED", "Requested token budget exceeds the project per-run limit.")
    now = _now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    active_count = db.query(ApiInvocation).filter(
        ApiInvocation.project_id == principal.project_id,
        ApiInvocation.status.in_(_ACTIVE_INVOCATION_STATUSES),
    ).count()
    if active_count >= quota.max_concurrent_runs:
        raise PlatformError("CONCURRENCY_QUOTA_EXCEEDED", "Project concurrent execution quota is exhausted.")
    if _usage_total(db, principal.project_id, day_start) + _reserved_total(db, principal.project_id, day_start) + requested_tokens > quota.daily_token_limit:
        raise PlatformError("DAILY_QUOTA_EXCEEDED", "Project daily token quota is exhausted.")
    if _usage_total(db, principal.project_id, month_start) + _reserved_total(db, principal.project_id, month_start) + requested_tokens > quota.monthly_token_limit:
        raise PlatformError("MONTHLY_QUOTA_EXCEEDED", "Project monthly token quota is exhausted.")
    invocation = ApiInvocation(
        id=_id(), project_id=principal.project_id, api_key_id=principal.key_id,
        user_id=principal.user_id, idempotency_key=idempotency_key, request_hash=request_hash,
        agent_id=agent_id, reserved_tokens=requested_tokens, status="PENDING",
    )
    db.add(invocation)
    db.flush()
    return invocation, False


def finalize_invocation(db: Session, invocation: ApiInvocation, run: object) -> ApiInvocation:
    """Persist a terminal invocation response and append exactly one token fact."""
    if invocation.status in {"COMPLETED", "FAILED", "TIMEOUT", "CANCELLED"}:
        return invocation
    status = str(getattr(run, "status", "FAILED"))
    usage = dict(getattr(run, "token_usage", {}) or {})
    used_tokens = max(0, int(usage.get("total", 0) or 0))
    invocation.status = status
    invocation.completed_at = _now()
    invocation.response_json = json.dumps({
        "run_id": getattr(run, "run_id", None), "status": status,
        "output": getattr(run, "output", None), "token_usage": usage,
    }, ensure_ascii=False)
    invocation.error_code = "RUN_NOT_COMPLETED" if status not in {"COMPLETED", "TIMEOUT", "CANCELLED"} else None
    # Record zero-token terminal attempts as well: an append-only fact must
    # explain every idempotent invocation, not only providers that report usage.
    db.add(UsageLedger(
        id=_id(), project_id=invocation.project_id, invocation_id=invocation.id,
        run_id=getattr(run, "run_id", None), idempotency_key=invocation.idempotency_key,
        metric_type="tokens", quantity=used_tokens, unit_price_version="trial-v1",
        metadata_redacted=json.dumps({"source": "agent_run", "status": status}),
    ))
    db.flush()
    return invocation


def usage_summary(db: Session, project: ApiProject) -> dict:
    quota = get_quota(db, project.id)
    now = _now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    return {
        "project_id": project.id,
        "daily_tokens": _usage_total(db, project.id, day_start),
        "monthly_tokens": _usage_total(db, project.id, month_start),
        "reserved_tokens": _reserved_total(db, project.id, day_start),
        "quota": quota.to_dict(),
        "records": [row.to_dict() for row in db.query(UsageLedger).filter_by(project_id=project.id).order_by(UsageLedger.occurred_at.desc()).limit(100).all()],
    }


__all__ = [
    "ApiPrincipal", "PlatformError", "authenticate_project_key", "create_organization",
    "create_project", "get_owned_organization", "get_owned_project", "issue_project_key",
    "revoke_project_key", "bind_project_agent", "is_project_agent_bound", "update_quota",
    "prepare_invocation", "finalize_invocation", "usage_summary", "_canonical_request_hash",
]
