"""Versioned, project-scoped Agent API control plane and invocation endpoint."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from core.api_contracts import correlation_id, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Header, status
from models.records import ApiInvocation, ApiProject, Organization, ProjectApiKey, User
from pydantic import BaseModel, Field
from services.agent_runtime_service import get_agent_runtime
from services.api_platform import (
    PlatformError,
    _canonical_request_hash,
    authenticate_project_key,
    bind_project_agent,
    create_organization,
    create_project,
    finalize_invocation,
    get_owned_organization,
    get_owned_project,
    is_project_agent_bound,
    issue_project_key,
    prepare_invocation,
    revoke_project_key,
    update_quota,
    usage_summary,
)
from services.audit_log import record_control_plane_operation
from sqlalchemy.orm import Session

router = APIRouter(tags=["platform-v2"])
logger = logging.getLogger(__name__)
DBSession = Annotated[Session, Depends(get_db)]


class OrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    environment: str = Field(default="live", pattern="^(test|live)$")


class ProjectAgentRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)


class ApiKeyRequest(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["agent:run", "usage:read"], max_length=8)
    expires_at: dt.datetime | None = None


class RevokeKeyRequest(BaseModel):
    confirm: bool = False


class QuotaRequest(BaseModel):
    max_concurrent_runs: int = Field(ge=1, le=100)
    daily_token_limit: int = Field(ge=1, le=100_000_000)
    monthly_token_limit: int = Field(ge=1, le=1_000_000_000)
    per_run_token_limit: int = Field(ge=1, le=1_000_000)


class ApiRunRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    input: str = Field(min_length=1, max_length=32_000)
    max_tokens: int = Field(default=2048, ge=1, le=1_000_000)


def _platform_problem(error: PlatformError, correlation: str):
    if error.code in {"API_KEY_INVALID"}:
        raise problem(status.HTTP_401_UNAUTHORIZED, error.code, error.message, correlation=correlation)
    if error.code in {"API_KEY_SCOPE_DENIED", "AGENT_PROJECT_SCOPE_DENIED"}:
        raise problem(status.HTTP_403_FORBIDDEN, error.code, error.message, correlation=correlation)
    if error.code.endswith("QUOTA_EXCEEDED"):
        raise problem(status.HTTP_429_TOO_MANY_REQUESTS, error.code, error.message, correlation=correlation)
    if error.code.endswith("CONFLICT") or error.code == "IDEMPOTENCY_KEY_REUSED":
        raise problem(status.HTTP_409_CONFLICT, error.code, error.message, correlation=correlation)
    if error.code.endswith("NOT_FOUND"):
        raise problem(status.HTTP_404_NOT_FOUND, error.code, error.message, correlation=correlation)
    raise problem(status.HTTP_400_BAD_REQUEST, error.code, error.message, correlation=correlation)


def _authenticated_project(db: Session, api_key: str | None, scope: str, correlation: str):
    try:
        return authenticate_project_key(db, api_key, scope)
    except PlatformError as error:
        _platform_problem(error, correlation)


@router.post("/organizations")
def create_org(req: OrganizationRequest, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        organization = create_organization(db, user, req.name)
        record_control_plane_operation(
            db, user_id=user.id, action="platform.organization.create", object_type="organization",
            object_id=organization.id, correlation_id=correlation, metadata={"name_present": True},
        )
        db.commit()
        return {"organization": organization.to_dict(), "correlation_id": correlation}
    except PlatformError as error:
        db.rollback()
        _platform_problem(error, correlation)


@router.get("/organizations")
def list_orgs(db: DBSession, user: User = Depends(get_current_user)):
    return {"organizations": [item.to_dict() for item in db.query(Organization).filter_by(owner_user_id=user.id).order_by(Organization.created_at.desc()).all()]}


@router.post("/organizations/{organization_id}/projects")
def create_api_project(organization_id: str, req: ProjectRequest, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        project = create_project(db, get_owned_organization(db, organization_id, user.id), user, req.name, req.environment)
        record_control_plane_operation(
            db, user_id=user.id, action="platform.project.create", object_type="api_project",
            object_id=project.id, correlation_id=correlation, metadata={"environment": project.environment},
        )
        db.commit()
        return {"project": project.to_dict(), "correlation_id": correlation}
    except PlatformError as error:
        db.rollback()
        _platform_problem(error, correlation)


@router.get("/projects")
def list_projects(db: DBSession, user: User = Depends(get_current_user)):
    projects = db.query(ApiProject).filter_by(owner_user_id=user.id).order_by(ApiProject.created_at.desc()).all()
    return {"projects": [project.to_dict() for project in projects]}


@router.post("/projects/{project_id}/agents")
def bind_agent_to_project(project_id: str, req: ProjectAgentRequest, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        project = get_owned_project(db, project_id, user.id)
        binding = bind_project_agent(db, project, user, req.agent_id)
        record_control_plane_operation(
            db, user_id=user.id, action="platform.agent.bind", object_type="project_agent_binding",
            object_id=binding.id, correlation_id=correlation, metadata={"agent_bound": True},
        )
        db.commit()
        return {"binding": binding.to_dict(), "correlation_id": correlation}
    except PlatformError as error:
        db.rollback()
        _platform_problem(error, correlation)


@router.get("/projects/{project_id}/agents")
def list_project_agents(project_id: str, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        project = get_owned_project(db, project_id, user.id)
        from models.records import ProjectAgentBinding
        bindings = db.query(ProjectAgentBinding).filter_by(project_id=project.id).order_by(ProjectAgentBinding.created_at.desc()).all()
        return {"bindings": [binding.to_dict() for binding in bindings], "correlation_id": correlation}
    except PlatformError as error:
        _platform_problem(error, correlation)


@router.post("/projects/{project_id}/keys")
def create_project_key(project_id: str, req: ApiKeyRequest, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        key, raw_key = issue_project_key(db, get_owned_project(db, project_id, user.id), user, req.name, req.scopes, req.expires_at)
        record_control_plane_operation(
            db, user_id=user.id, action="platform.key.create", object_type="project_api_key",
            object_id=key.id, correlation_id=correlation,
            metadata={"scope_count": len(key.to_dict()["scopes"]), "has_expiry": key.expires_at is not None},
        )
        db.commit()
        # ``secret`` is returned only here and is intentionally excluded from list responses.
        return {"api_key": key.to_dict(), "secret": raw_key, "correlation_id": correlation}
    except PlatformError as error:
        db.rollback()
        _platform_problem(error, correlation)


@router.get("/projects/{project_id}/keys")
def list_project_keys(project_id: str, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        project = get_owned_project(db, project_id, user.id)
        keys = db.query(ProjectApiKey).filter_by(project_id=project.id).order_by(ProjectApiKey.created_at.desc()).all()
        return {"keys": [key.to_dict() for key in keys], "correlation_id": correlation}
    except PlatformError as error:
        _platform_problem(error, correlation)


@router.post("/projects/{project_id}/keys/{key_id}/revoke")
def revoke_key(project_id: str, key_id: str, req: RevokeKeyRequest, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    if not req.confirm:
        raise problem(status.HTTP_409_CONFLICT, "API_KEY_REVOKE_CONFIRMATION_REQUIRED", "Set confirm=true to revoke an API key.", correlation=correlation)
    try:
        key = revoke_project_key(db, key_id, get_owned_project(db, project_id, user.id))
        record_control_plane_operation(
            db, user_id=user.id, action="platform.key.revoke", object_type="project_api_key",
            object_id=key.id, correlation_id=correlation, metadata={"confirmed": True},
        )
        db.commit()
        return {"api_key": key.to_dict(), "correlation_id": correlation}
    except PlatformError as error:
        db.rollback()
        _platform_problem(error, correlation)


@router.put("/projects/{project_id}/quota")
def set_project_quota(project_id: str, req: QuotaRequest, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        project = get_owned_project(db, project_id, user.id)
        quota = update_quota(db, project, user, **req.model_dump())
        record_control_plane_operation(
            db, user_id=user.id, action="platform.quota.update", object_type="project_quota",
            object_id=project.id, correlation_id=correlation,
            metadata={key: getattr(quota, key) for key in ("max_concurrent_runs", "daily_token_limit", "monthly_token_limit", "per_run_token_limit")},
        )
        db.commit()
        return {"project_id": project.id, "quota": quota.to_dict(), "correlation_id": correlation}
    except PlatformError as error:
        db.rollback()
        _platform_problem(error, correlation)


@router.get("/projects/{project_id}/usage")
def get_project_usage(project_id: str, db: DBSession, user: User = Depends(get_current_user)):
    correlation = correlation_id()
    try:
        return {**usage_summary(db, get_owned_project(db, project_id, user.id)), "correlation_id": correlation}
    except PlatformError as error:
        _platform_problem(error, correlation)


@router.post("/runs")
async def invoke_agent_run(
    req: ApiRunRequest,
    db: DBSession,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Synchronously invoke one project-owned Agent Run through an API key."""
    correlation = correlation_id()
    principal = _authenticated_project(db, x_api_key, "agent:run", correlation)
    request_hash = _canonical_request_hash(req.agent_id, req.input, req.max_tokens)
    try:
        if not is_project_agent_bound(db, principal.project_id, principal.user_id, req.agent_id):
            raise PlatformError("AGENT_PROJECT_SCOPE_DENIED", "Agent is not authorized for this project.")
        invocation, replayed = prepare_invocation(
            db, principal, idempotency_key=idempotency_key or "", request_hash=request_hash,
            agent_id=req.agent_id, requested_tokens=req.max_tokens,
        )
        if replayed:
            db.commit()
            return {"invocation": invocation.to_dict(), "replayed": True, "correlation_id": correlation}
        runtime = get_agent_runtime()
        agent = runtime.agent_store.get(req.agent_id, user_id=principal.user_id)
        if agent is None:
            invocation.status = "FAILED"
            invocation.error_code = "AGENT_NOT_FOUND"
            db.commit()
            raise PlatformError("AGENT_NOT_FOUND", "Agent was not found.")
        # Reservation must commit before the runtime opens its independent DB
        # session; retaining this write transaction would deadlock SQLite.
        invocation.status = "RUNNING"
        db.commit()
        run = runtime.create_run(
            agent_id=req.agent_id,
            input_text=req.input,
            user_id=principal.user_id,
            metadata={"api_project_id": principal.project_id, "api_invocation_id": invocation.id},
            execute=False,
        )
        invocation.run_id = run.run_id
        db.commit()
        await runtime.execute_run(run.run_id)
        stored = runtime.get_run(run.run_id, user_id=principal.user_id)
        finalize_invocation(db, invocation, stored)
        db.commit()
        return {"invocation": invocation.to_dict(), "replayed": False, "correlation_id": correlation}
    except PlatformError as error:
        db.rollback()
        _platform_problem(error, correlation)
    except Exception:
        db.rollback()
        logger.exception("Project API invocation failed", extra={"correlation_id": correlation})
        raise problem(status.HTTP_503_SERVICE_UNAVAILABLE, "API_RUN_UNAVAILABLE", "Agent run could not be completed.", correlation=correlation)


@router.get("/runs/{invocation_id}")
def get_invocation(
    invocation_id: str,
    db: DBSession,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    correlation = correlation_id()
    principal = _authenticated_project(db, x_api_key, "agent:run", correlation)
    invocation = db.query(ApiInvocation).filter_by(id=invocation_id, project_id=principal.project_id).first()
    if invocation is None:
        raise problem(status.HTTP_404_NOT_FOUND, "API_INVOCATION_NOT_FOUND", "Invocation was not found.", correlation=correlation)
    return {"invocation": invocation.to_dict(), "correlation_id": correlation}
