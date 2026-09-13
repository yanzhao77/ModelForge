"""AgentDefinition + AgentRun REST surface (V1.1).

This router is the roadmap's `/api/v1/agents` contract. The pre-existing
`/api/v1/agent/*` routes stay untouched so existing desktop builds keep working;
both write the same `agents` table and drive the same Agent runtime.
"""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import Session, User
from pydantic import BaseModel, Field
from services.agent_run_service import AgentRunService
from services.agent_service import AgentService, AgentServiceError
from services.audit_log import record_operation
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    model: str | None = Field(default=None, max_length=255)
    model_id: int | None = None
    model_target: dict | None = None
    system_prompt: str | None = Field(default=None, max_length=20000)
    tools: list[str] = Field(default_factory=list, max_length=64)
    memory_config: dict | None = None
    knowledge_config: dict | None = None
    policy: dict | None = None
    runtime_config: dict | None = None
    status: str = Field(default="active", max_length=20)


class AgentUpdateRequest(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    model: str | None = Field(default=None, max_length=255)
    model_id: int | None = None
    model_target: dict | None = None
    system_prompt: str | None = Field(default=None, max_length=20000)
    tools: list[str] | None = Field(default=None, max_length=64)
    memory_config: dict | None = None
    knowledge_config: dict | None = None
    policy: dict | None = None
    runtime_config: dict | None = None
    status: str | None = Field(default=None, max_length=20)


class AgentRunCreateRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    session_id: int | None = None
    metadata: dict | None = None
    execute: bool = True
    confirm: bool = True
    request_id: str | None = Field(default=None, max_length=64)


def _service(db: DBSession) -> AgentService:
    from services.agent_engine import get_engine
    from services.agent_runtime_service import get_agent_runtime

    return AgentService(db, runtime=get_agent_runtime(), engine=get_engine())


def _runs(db: DBSession) -> AgentRunService:
    from services.agent_runtime_service import get_agent_runtime

    return AgentRunService(db, runtime=get_agent_runtime())


def _agent_problem(exc: AgentServiceError, corr: str):
    return problem(exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None)


@router.get("")
def list_agents(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"agents": _service(db).list(user.id, limit=limit, offset=offset)}


@router.post("")
async def create_agent(
    req: AgentCreateRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    payload = req.model_dump()
    try:
        agent = _service(db).create(user.id, payload)
    except AgentServiceError as exc:
        raise _agent_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="agents.create",
        object_type="agent",
        object_id=agent["name"],
        correlation_id=corr,
        metadata={"model_id": agent.get("model_id"), "tool_count": len(agent.get("tools") or [])},
    )
    db.commit()
    return operation_result(agent, corr)


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return _runs(db).get_run(run_id, user.id)
    except AgentServiceError as exc:
        raise _agent_problem(exc, correlation_id()) from exc


@router.get("/runs/{run_id}/trace")
def get_run_trace(
    run_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return _runs(db).trace(run_id, user.id)
    except AgentServiceError as exc:
        raise _agent_problem(exc, correlation_id()) from exc


@router.get("/{agent_id}")
def get_agent(
    agent_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return AgentService._payload(_service(db).require(agent_id, user.id))
    except AgentServiceError as exc:
        raise _agent_problem(exc, correlation_id()) from exc


@router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    req: AgentUpdateRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    payload = {key: value for key, value in req.model_dump().items() if value is not None}
    try:
        agent = _service(db).update(user.id, agent_id, payload)
    except AgentServiceError as exc:
        raise _agent_problem(exc, corr) from exc
    record_operation(db, user_id=user.id, action="agents.update", object_type="agent", object_id=agent_id, correlation_id=corr)
    db.commit()
    return operation_result(agent, corr)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    if not _service(db).delete(user.id, agent_id):
        raise problem(404, "AGENT_NOT_FOUND", "Agent not found.", correlation=corr)
    record_operation(db, user_id=user.id, action="agents.delete", object_type="agent", object_id=agent_id, correlation_id=corr)
    db.commit()
    return operation_result({"ok": True}, corr)


@router.get("/{agent_id}/runs")
def list_agent_runs(
    agent_id: str,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        _service(db).require(agent_id, user.id)
    except AgentServiceError as exc:
        raise _agent_problem(exc, correlation_id()) from exc
    return {"runs": _runs(db).list_runs(user.id, agent_id=agent_id, status=status, limit=limit, offset=offset)}


@router.post("/{agent_id}/runs")
async def create_agent_run(
    agent_id: str,
    req: AgentRunCreateRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "AGENT_RUN_CONFIRMATION_REQUIRED", "Confirm before creating an Agent Run.", correlation=corr)
    if req.session_id is not None:
        owned = (
            db.query(Session)
            .filter(Session.id == req.session_id, Session.user_id == user.id, Session.is_active.is_(True))
            .first()
        )
        if owned is None:
            raise problem(404, "SESSION_NOT_FOUND", "Session not found.", correlation=corr)
    try:
        _service(db).require(agent_id, user.id)
        result = _runs(db).create_run(
            agent_id=agent_id,
            input_text=req.input,
            user_id=user.id,
            session_id=req.session_id,
            metadata=req.metadata,
            execute=req.execute,
        )
    except AgentServiceError as exc:
        raise _agent_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="agents.run.create",
        object_type="agent_run",
        object_id=result["run_id"],
        correlation_id=corr,
        metadata={"agent_id": agent_id, "execute": bool(req.execute)},
    )
    db.commit()
    return operation_result(result, corr)


@router.get("/{agent_id}/versions")
def agent_versions(
    agent_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from models.records import AgentDefinitionVersion

    try:
        _service(db).require(agent_id, user.id)
    except AgentServiceError as exc:
        raise _agent_problem(exc, correlation_id()) from exc
    rows = (
        db.query(AgentDefinitionVersion)
        .filter(AgentDefinitionVersion.user_id == user.id, AgentDefinitionVersion.agent_name == agent_id)
        .order_by(AgentDefinitionVersion.version.desc())
        .all()
    )
    return {"agent_id": agent_id, "versions": [item.to_dict() for item in rows]}
