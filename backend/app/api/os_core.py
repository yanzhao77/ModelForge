"""V4.0 unified OS API surface."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import record_operation
from services.os_core_service import OSCoreService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(tags=["os-core"])


class EventEmitRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    subject_id: str | None = Field(default=None, max_length=160)
    payload: dict = Field(default_factory=dict)


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    tools: list[str] = Field(default_factory=list, max_length=100)
    prompt: str | None = Field(default=None, max_length=20000)
    knowledge: list[str] = Field(default_factory=list, max_length=100)
    workflow_id: str | None = Field(default=None, max_length=64)
    evaluation: dict = Field(default_factory=dict)


def _service(db: DBSession) -> OSCoreService:
    return OSCoreService(db)


@router.get("/resources")
def list_resources(
    type: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"resources": _service(db).resources(user.id, resource_type=type, limit=limit)}


@router.get("/processes")
def list_processes(
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"processes": _service(db).processes(user.id, status=status, limit=limit)}


@router.get("/os/events")
def list_events(
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"events": _service(db).events(user.id, event_type=event_type, limit=limit)}


@router.post("/os/events")
def emit_event(req: EventEmitRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    event = _service(db).emit_event(user.id, req.event_type, req.subject_id, req.payload)
    record_operation(db, user_id=user.id, action="event.emit", object_type="event", object_id=event["event_id"], correlation_id=corr, metadata={"event_type": event["event_type"]})
    db.commit()
    return operation_result(event, corr)


@router.get("/dashboard/v4")
def v4_dashboard(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return _service(db).dashboard(user.id)


@router.get("/skills")
def list_skills(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"skills": _service(db).skills(user.id)}


@router.post("/skills")
def create_skill(req: SkillCreateRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        skill = _service(db).create_skill(user.id, req.model_dump())
    except ValueError as exc:
        raise problem(400, str(exc), "Skill could not be created.", correlation=corr) from exc
    record_operation(db, user_id=user.id, action="skill.create", object_type="skill", object_id=skill["skill_id"], correlation_id=corr, metadata={"tool_count": len(skill.get("tools") or [])})
    db.commit()
    return operation_result(skill, corr)
