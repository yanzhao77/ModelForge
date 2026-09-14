"""Autonomous Goal and approval API (V3.4)."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import record_operation
from services.goal_service import (
    DECISIONS,
    GOAL_STATUSES,
    RISKS,
    GoalService,
    GoalServiceError,
)
from sqlalchemy.orm import Session as DBSession

router = APIRouter(tags=["goals"])


class GoalCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    priority: str = Field(default="normal", max_length=16)
    deadline: str | None = Field(default=None, max_length=64)
    constraints: list[str] = Field(default_factory=list, max_length=100)
    success_criteria: list[str] = Field(default_factory=list, max_length=100)
    sub_goals: list[dict] = Field(default_factory=list, max_length=100)
    decompose: bool = True


class GoalTransitionRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)


class ApprovalCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    goal_id: str | None = Field(default=None, max_length=64)
    action: str = Field(min_length=1, max_length=160)
    risk: str = Field(default="HIGH", max_length=16)
    details: dict = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(min_length=1, max_length=24)
    modifications: dict | None = None
    comment: str | None = Field(default=None, max_length=4000)


def _service(db: DBSession) -> GoalService:
    return GoalService(db)


def _goal_problem(exc: GoalServiceError, corr: str):
    return problem(exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None)


@router.get("/goals")
def list_goals(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"goals": _service(db).list(user.id, status=status, limit=limit), "statuses": sorted(GOAL_STATUSES)}


@router.post("/goals")
def create_goal(req: GoalCreateRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        goal = _service(db).create(user.id, req.model_dump())
    except GoalServiceError as exc:
        raise _goal_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="goal.create",
        object_type="goal",
        object_id=goal["goal_id"],
        correlation_id=corr,
        metadata={"agent_id": goal["agent_id"], "status": goal["status"]},
    )
    db.commit()
    return operation_result(goal, corr)


@router.get("/goals/{goal_id}")
def get_goal(goal_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return _service(db).get(user.id, goal_id)
    except GoalServiceError as exc:
        raise _goal_problem(exc, correlation_id()) from exc


@router.post("/goals/{goal_id}/transition")
def transition_goal(goal_id: str, req: GoalTransitionRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        goal = _service(db).transition(user.id, goal_id, req.status)
    except GoalServiceError as exc:
        raise _goal_problem(exc, corr) from exc
    record_operation(db, user_id=user.id, action="goal.transition", object_type="goal", object_id=goal_id, correlation_id=corr, metadata={"status": goal["status"]})
    db.commit()
    return operation_result(goal, corr)


@router.get("/approvals")
def approval_options():
    return {"risks": sorted(RISKS), "decisions": sorted(DECISIONS)}


@router.post("/approvals")
def create_approval(req: ApprovalCreateRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        approval = _service(db).create_approval(user.id, req.model_dump())
    except GoalServiceError as exc:
        raise _goal_problem(exc, corr) from exc
    record_operation(db, user_id=user.id, action="approval.create", object_type="approval", object_id=approval["approval_id"], correlation_id=corr, metadata={"risk": approval["risk"]})
    db.commit()
    return operation_result(approval, corr)


@router.post("/approvals/{approval_id}/decision")
def decide_approval(approval_id: str, req: ApprovalDecisionRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        result = _service(db).decide_approval(user.id, approval_id, req.model_dump())
    except GoalServiceError as exc:
        raise _goal_problem(exc, corr) from exc
    record_operation(db, user_id=user.id, action="approval.decide", object_type="approval", object_id=approval_id, correlation_id=corr, metadata={"decision": result["decision"]["decision"]})
    db.commit()
    return operation_result(result, corr)
