"""Agent Learning API (V3.3)."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import User
from pydantic import BaseModel, Field
from services.agent_learning_service import (
    OUTCOMES,
    AgentLearningError,
    AgentLearningService,
)
from services.audit_log import record_operation
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/agent-experiences", tags=["agent-learning"])


class ExperienceRecordRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    task_id: str | None = Field(default=None, max_length=64)
    goal: str = Field(min_length=1, max_length=4000)
    context: dict | None = None
    strategy: dict | None = None
    steps: list = Field(default_factory=list, max_length=200)
    tools: list[str] = Field(default_factory=list, max_length=100)
    result: dict | str | None = None
    outcome: str = Field(default="PARTIAL_SUCCESS", max_length=32)
    score: float | None = None
    failure_reason: str | None = Field(default=None, max_length=4000)
    reflection: str | None = Field(default=None, max_length=12000)
    metrics: dict | None = None
    human_rating: float | None = None


class RecommendationRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)


def _service(db: DBSession) -> AgentLearningService:
    return AgentLearningService(db)


def _learning_problem(exc: AgentLearningError, corr: str):
    return problem(exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None)


@router.get("")
def list_experiences(
    agent_id: str | None = None,
    outcome: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"experiences": _service(db).list(user.id, agent_id=agent_id, outcome=outcome, limit=limit), "outcomes": sorted(OUTCOMES)}


@router.post("")
def record_experience(req: ExperienceRecordRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        experience = _service(db).record(user.id, req.model_dump())
    except AgentLearningError as exc:
        raise _learning_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="agent_experience.record",
        object_type="agent_experience",
        object_id=experience["experience_id"],
        correlation_id=corr,
        metadata={"agent_id": experience["agent_id"], "outcome": experience["outcome"]},
    )
    db.commit()
    return operation_result(experience, corr)


@router.post("/recommend")
def recommend_experience(req: RecommendationRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return _service(db).recommend(user.id, agent_id=req.agent_id, goal=req.goal, limit=req.limit)
