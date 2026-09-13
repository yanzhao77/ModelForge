"""Workflow / Multi-Agent REST surface (V1.5)."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import record_operation
from services.workflow_engine import NODE_TYPES, validate_definition
from services.workflow_service import WorkflowService, WorkflowServiceError
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    definition: dict
    status: str = Field(default="active", max_length=20)


class WorkflowUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    definition: dict | None = None
    status: str | None = Field(default=None, max_length=20)


class WorkflowRunRequest(BaseModel):
    input: dict = Field(default_factory=dict)
    execute: bool = True
    confirm: bool = True
    request_id: str | None = Field(default=None, max_length=64)


def _service(db: DBSession) -> WorkflowService:
    return WorkflowService(db)


def _problem(exc: WorkflowServiceError, corr: str):
    return exc.to_problem(corr)


@router.get("")
def list_workflows(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"workflows": _service(db).list(user.id, limit=limit, offset=offset), "node_types": list(NODE_TYPES)}


@router.post("")
def create_workflow(
    req: WorkflowCreateRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        workflow = _service(db).create(user.id, req.model_dump())
    except WorkflowServiceError as exc:
        raise _problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="workflow.create",
        object_type="workflow",
        object_id=workflow["workflow_id"],
        correlation_id=corr,
        metadata={"node_count": len((workflow.get("definition") or {}).get("nodes") or [])},
    )
    db.commit()
    return operation_result(workflow, corr)


@router.post("/validate")
def validate_workflow_definition(definition: dict, user: User = Depends(get_current_user)):
    """Validate a definition without persisting it."""
    del user
    problems = validate_definition(definition)
    return {"valid": not problems, "problems": problems, "node_types": list(NODE_TYPES)}


@router.get("/runs")
def list_all_runs(
    workflow_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"runs": _service(db).list_runs(user.id, workflow_id, limit=limit)}


@router.get("/runs/{run_id}")
def get_workflow_run(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return _service(db).get_run(user.id, run_id)
    except WorkflowServiceError as exc:
        raise _problem(exc, correlation_id()) from exc


@router.get("/runs/{run_id}/events")
def workflow_run_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return {"events": _service(db).events(user.id, run_id, after_sequence=after_sequence, limit=limit)}
    except WorkflowServiceError as exc:
        raise _problem(exc, correlation_id()) from exc


@router.get("/runs/{run_id}/trace")
def workflow_run_trace(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return _service(db).trace(user.id, run_id)
    except WorkflowServiceError as exc:
        raise _problem(exc, correlation_id()) from exc


@router.post("/runs/{run_id}/approve")
async def approve_workflow_run(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    corr = correlation_id()
    try:
        result = await _service(db).approve_run(user.id, run_id)
    except WorkflowServiceError as exc:
        raise _problem(exc, corr) from exc
    record_operation(
        db, user_id=user.id, action="workflow.approve", object_type="workflow_run",
        object_id=run_id, correlation_id=corr,
    )
    db.commit()
    return operation_result(result, corr)


@router.post("/runs/{run_id}/cancel")
def cancel_workflow_run(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    corr = correlation_id()
    try:
        result = _service(db).cancel_run(user.id, run_id)
    except WorkflowServiceError as exc:
        raise _problem(exc, corr) from exc
    record_operation(
        db, user_id=user.id, action="workflow.cancel", object_type="workflow_run",
        object_id=run_id, correlation_id=corr,
    )
    db.commit()
    return operation_result(result, corr)


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return _service(db).get(user.id, workflow_id)
    except WorkflowServiceError as exc:
        raise _problem(exc, correlation_id()) from exc


@router.put("/{workflow_id}")
def update_workflow(
    workflow_id: str,
    req: WorkflowUpdateRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    payload = {key: value for key, value in req.model_dump().items() if value is not None}
    try:
        workflow = _service(db).update(user.id, workflow_id, payload)
    except WorkflowServiceError as exc:
        raise _problem(exc, corr) from exc
    return operation_result(workflow, corr)


@router.delete("/{workflow_id}")
def delete_workflow(
    workflow_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    corr = correlation_id()
    try:
        _service(db).delete(user.id, workflow_id)
    except WorkflowServiceError as exc:
        raise _problem(exc, corr) from exc
    return operation_result({"ok": True, "workflow_id": workflow_id}, corr)


@router.get("/{workflow_id}/runs")
def list_workflow_runs(
    workflow_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        _service(db).require(user.id, workflow_id)
    except WorkflowServiceError as exc:
        raise _problem(exc, correlation_id()) from exc
    return {"runs": _service(db).list_runs(user.id, workflow_id, limit=limit)}


@router.post("/{workflow_id}/runs")
async def create_workflow_run(
    workflow_id: str,
    req: WorkflowRunRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "WORKFLOW_RUN_CONFIRMATION_REQUIRED", "Confirm before running a workflow.", correlation=corr)
    try:
        result = _service(db).create_run(
            user.id, workflow_id, run_input=req.input, execute=req.execute
        )
    except WorkflowServiceError as exc:
        raise _problem(exc, corr) from exc
    record_operation(
        db, user_id=user.id, action="workflow.run.create", object_type="workflow_run",
        object_id=result["run_id"], correlation_id=corr, metadata={"workflow_id": workflow_id},
    )
    db.commit()
    return operation_result(result, corr)
