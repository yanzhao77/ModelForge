"""Multi-Agent Team API (V3.1)."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import User
from pydantic import BaseModel, Field
from services.agent_team_service import (
    TEAM_ROLES,
    TEAM_STRATEGIES,
    AgentTeamError,
    AgentTeamService,
)
from services.audit_log import record_operation
from sqlalchemy.orm import Session as DBSession

router = APIRouter(tags=["agent-teams"])


class TeamMemberRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    role: str = Field(default="SPECIALIST", max_length=32)
    config: dict | None = None


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    manager_agent_id: str = Field(min_length=1, max_length=255)
    strategy: str = Field(default="SEQUENTIAL", max_length=32)
    max_concurrency: int = Field(default=1, ge=1, le=32)
    timeout: int | None = Field(default=None, ge=1)
    retry_policy: dict | None = None
    shared_memory_id: str | None = Field(default=None, max_length=64)
    permission_policy_id: str | None = Field(default=None, max_length=64)
    members: list[TeamMemberRequest] = Field(default_factory=list, max_length=64)


class TeamRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    execute: bool = True
    priority: str = Field(default="normal", max_length=16)
    idempotency_key: str | None = Field(default=None, max_length=128)


class DelegationRequest(BaseModel):
    delegate_agent_id: str = Field(min_length=1, max_length=255)
    instruction: str = Field(min_length=1, max_length=100_000)
    team_id: str | None = Field(default=None, max_length=64)
    priority: str = Field(default="normal", max_length=16)


class TaskCancelRequest(BaseModel):
    confirm: bool = False


def _service(db: DBSession) -> AgentTeamService:
    from services.agent_runtime_service import get_agent_runtime
    from services.agent_service import AgentService

    return AgentTeamService(db, agent_service=AgentService(db, runtime=get_agent_runtime()))


def _team_problem(exc: AgentTeamError, corr: str):
    return problem(exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None)


@router.get("/agent-teams")
def list_teams(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {
        "teams": _service(db).list(user.id, limit=limit, offset=offset),
        "roles": sorted(TEAM_ROLES),
        "strategies": sorted(TEAM_STRATEGIES),
    }


@router.post("/agent-teams")
def create_team(req: TeamCreateRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        team = _service(db).create_team(user.id, req.model_dump())
    except AgentTeamError as exc:
        raise _team_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="agent_team.create",
        object_type="agent_team",
        object_id=team["team_id"],
        correlation_id=corr,
        metadata={"manager_agent_id": team["manager_agent_id"], "member_count": len(team.get("members") or [])},
    )
    db.commit()
    return operation_result(team, corr)


@router.get("/agent-teams/{team_id}")
def get_team(team_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return _service(db).get_team(user.id, team_id)
    except AgentTeamError as exc:
        raise _team_problem(exc, correlation_id()) from exc


@router.post("/agent-teams/{team_id}/runs")
def create_team_run(
    team_id: str,
    req: TeamRunRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        run = _service(db).create_run(user.id, team_id, req.model_dump())
    except AgentTeamError as exc:
        raise _team_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="agent_team.run.create",
        object_type="agent_team_run",
        object_id=run["run_id"],
        correlation_id=corr,
        metadata={"team_id": team_id, "status": run["status"]},
    )
    db.commit()
    return operation_result(run, corr)


@router.get("/agent-teams/{team_id}/runs/{run_id}")
def get_team_run(
    team_id: str,
    run_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        run = _service(db).get_run(user.id, run_id)
    except AgentTeamError as exc:
        raise _team_problem(exc, correlation_id()) from exc
    if run["team_id"] != team_id:
        raise problem(404, "AGENT_TEAM_RUN_NOT_FOUND", "Agent team run not found.", correlation=correlation_id())
    return run


@router.get("/agent-teams/{team_id}/runs/{run_id}/trace")
def get_team_trace(
    team_id: str,
    run_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        trace = _service(db).trace(user.id, run_id)
    except AgentTeamError as exc:
        raise _team_problem(exc, correlation_id()) from exc
    if trace["run"]["team_id"] != team_id:
        raise problem(404, "AGENT_TEAM_RUN_NOT_FOUND", "Agent team run not found.", correlation=correlation_id())
    return trace


@router.post("/agents/{agent_id}/delegate")
def delegate_agent(
    agent_id: str,
    req: DelegationRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        result = _service(db).delegate(user.id, agent_id, req.model_dump())
    except AgentTeamError as exc:
        raise _team_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="agent.delegate",
        object_type="agent_delegation",
        object_id=result["delegation"]["delegation_id"],
        correlation_id=corr,
        metadata={"manager_agent_id": agent_id, "delegate_agent_id": req.delegate_agent_id, "team_id": req.team_id},
    )
    db.commit()
    return operation_result(result, corr)


@router.get("/agent-tasks/{task_id}")
def get_agent_task(task_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return _service(db).get_team_task(user.id, task_id)
    except AgentTeamError as exc:
        raise _team_problem(exc, correlation_id()) from exc


@router.post("/agent-tasks/{task_id}/cancel")
def cancel_agent_task(
    task_id: str,
    req: TaskCancelRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    if not req.confirm:
        raise problem(409, "AGENT_TASK_CANCEL_CONFIRMATION_REQUIRED", "Confirm before cancelling an agent task.", correlation=corr)
    try:
        result = _service(db).cancel_team_task(user.id, task_id)
    except AgentTeamError as exc:
        raise _team_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="agent_task.cancel",
        object_type="agent_task",
        object_id=task_id,
        correlation_id=corr,
        metadata={"confirmed": True},
    )
    db.commit()
    return operation_result(result, corr)
