"""Training API routes: start/status/stream/stop/register/templates/tasks."""
import asyncio
import json

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import (
    AuditMetadataRejected,
    AuditPersistenceError,
    commit_control_plane_audit,
    record_control_plane_operation,
    validate_control_plane_audit_metadata,
)
from services.task_service import project_legacy_tasks
from services.training import TrainingService, get_log_tail
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/train", tags=["train"])


class TrainStartRequest(BaseModel):
    dataset_id: int | None = None
    dataset_path: str | None = None
    base_model: str
    method: str = "lora"  # full | lora
    epochs: int = 3
    learning_rate: float = 2e-5
    batch_size: int = 2
    lora_r: int | None = 8
    lora_alpha: int | None = 32
    target_modules: list | None = None
    output_dir: str = "./outputs"
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


class TrainActionRequest(BaseModel):
    """Explicit confirmation boundary for user-initiated training actions."""

    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


def _task_or_404(db, task_id, user):
    row = TrainingService().get(db, task_id, user.id)
    if row is None:
        raise problem(404, "TRAINING_TASK_NOT_FOUND", "Training task was not found.")
    return row


@router.post("/start")
def train_start(
    req: TrainStartRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "TRAINING_START_CONFIRMATION_REQUIRED", "Confirm before starting training.", correlation=corr)
    audit_metadata = {"confirmed": True, "dataset_bound": req.dataset_id is not None, "method": req.method}
    try:
        validate_control_plane_audit_metadata("training.start", audit_metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=corr) from exc
    try:
        row = TrainingService().start(db, user.id, req.model_dump(exclude={"confirm", "request_id"}))
        project_legacy_tasks(db, user.id)
        record_control_plane_operation(db, user_id=user.id, action="training.start", object_type="training_task", object_id=row.task_id, correlation_id=corr, metadata=audit_metadata)
        commit_control_plane_audit(db)
        return operation_result(row.to_dict(), corr)
    except (AuditMetadataRejected, AuditPersistenceError) as exc:
        raise problem(503, "TRAINING_START_AUDIT_DURABILITY_UNKNOWN", "Training start was accepted, but audit durability is unknown.", correlation=corr) from exc
    except (RuntimeError, ValueError) as error:
        raise problem(400, "TRAINING_START_REJECTED", "Training start was not accepted.", correlation=corr) from error


@router.get("/tasks")
def train_tasks(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    project_legacy_tasks(db, user.id)
    return [t.to_dict() for t in TrainingService().list(db, user.id)]


@router.get("/status/{task_id}")
def train_status(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _task_or_404(db, task_id, user)
    data = row.to_dict()
    data["log_tail"] = get_log_tail(row.log_path)
    return data


@router.get("/stream/{task_id}")
async def train_stream(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _task_or_404(db, task_id, user)
    log_path = row.log_path or ""
    state_path = ""
    if row.output_dir:
        import os
        state_path = os.path.join(row.output_dir, "state.json")

    async def event_generator():
        last_pos = 0
        last_state = None
        while True:
            # tail log
            if log_path:
                import os
                if os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_pos)
                        new_lines = f.read()
                        last_pos = f.tell()
                    if new_lines:
                        for line in new_lines.splitlines():
                            yield f"data: {json.dumps({'type': 'log', 'data': line}, ensure_ascii=False)}\n\n"
            # state
            state = {}
            if state_path:
                import os
                if os.path.exists(state_path):
                    try:
                        with open(state_path, "r", encoding="utf-8") as f:
                            state = json.load(f)
                    except Exception:
                        state = {}
            if state != last_state and state:
                last_state = state
                yield f"data: {json.dumps({'type': 'progress', 'data': state}, ensure_ascii=False)}\n\n"
            # terminal?
            cur = row.status
            if cur in ("done", "error", "stopped"):
                yield f"data: {json.dumps({'type': 'done', 'data': {'status': cur}}, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stop/{task_id}")
def train_stop(
    task_id: str, req: TrainActionRequest | None = None, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "TRAINING_STOP_CONFIRMATION_REQUIRED", "Confirm before stopping training.", correlation=corr)
    audit_metadata = {"confirmed": True}
    try:
        validate_control_plane_audit_metadata("training.stop", audit_metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=corr) from exc
    _task_or_404(db, task_id, user)
    ok = TrainingService().stop(db, task_id, user.id)
    try:
        record_control_plane_operation(db, user_id=user.id, action="training.stop", object_type="training_task", object_id=task_id, correlation_id=corr, metadata=audit_metadata)
        commit_control_plane_audit(db)
    except (AuditMetadataRejected, AuditPersistenceError) as exc:
        raise problem(503, "TRAINING_STOP_AUDIT_DURABILITY_UNKNOWN", "Training stop was accepted, but audit durability is unknown.", correlation=corr) from exc
    return operation_result({"ok": ok}, corr)


@router.post("/{task_id}/register-model")
def train_register_model(
    task_id: str, req: TrainActionRequest | None = None, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "TRAINING_REGISTER_CONFIRMATION_REQUIRED", "Confirm before registering a training model.", correlation=corr)
    audit_metadata = {"confirmed": True}
    try:
        validate_control_plane_audit_metadata("training.register_model", audit_metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=corr) from exc
    try:
        model = TrainingService().register_model(db, task_id, user.id)
        record_control_plane_operation(db, user_id=user.id, action="training.register_model", object_type="training_task", object_id=task_id, correlation_id=corr, metadata=audit_metadata)
        commit_control_plane_audit(db)
        return operation_result(model, corr)
    except (AuditMetadataRejected, AuditPersistenceError) as exc:
        raise problem(503, "TRAINING_REGISTER_AUDIT_DURABILITY_UNKNOWN", "Training model registration was accepted, but audit durability is unknown.", correlation=corr) from exc
    except ValueError as error:
        raise problem(400, "TRAINING_REGISTER_REJECTED", "Training model registration was not accepted.", correlation=corr) from error


@router.get("/templates")
def train_templates(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return TrainingService.templates()
