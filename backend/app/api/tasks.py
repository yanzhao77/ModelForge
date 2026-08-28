"""Global persisted task center and onboarding API routes."""
from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import SessionLocal, get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from models.records import AgentRun, ModelRecord, TaskRecord, User
from models.records import Session as ChatSession
from pydantic import BaseModel, Field
from services.audit_log import (
    AuditMetadataRejected,
    AuditPersistenceError,
    commit_control_plane_audit,
    record_control_plane_operation,
    validate_control_plane_audit_metadata,
)
from services.task_execution import RetryExecutionError, TaskExecutionService
from services.task_realtime import task_event_hub, task_outbox_publisher
from services.task_service import TaskConflict, TaskService, project_legacy_tasks
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/tasks", tags=["tasks"])
_SSE_REPLAY_BATCH = 100
_SSE_MAX_EVENTS_PER_CONNECTION = 1000
service = TaskService()
executor = TaskExecutionService(service)


class TaskCreateRequest(BaseModel):
    task_type: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    source: str = Field(default="manual", min_length=2, max_length=64)
    summary: str | None = Field(default=None, max_length=2000)
    metadata: dict = Field(default_factory=dict)
    cancelable: bool = False
    retryable: bool = False
    priority: str = "normal"
    idempotency_key: str | None = Field(default=None, max_length=128)


class TaskTransitionRequest(BaseModel):
    status: str
    summary: str | None = Field(default=None, max_length=2000)
    progress_current: int | None = None
    progress_total: int | None = None
    progress_unit: str | None = Field(default=None, max_length=32)
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    result: dict | None = None
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=4000)
    error_detail: dict | None = None
    required_action: dict | None = None
    expected_version: int | None = Field(default=None, ge=1)


class TaskBatchRetryRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=50)
    expected_versions: dict[str, int] = Field(default_factory=dict, max_length=50)
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


class TaskActionRequest(BaseModel):
    """Explicit confirmation boundary for user-initiated task actions."""

    confirm: bool = False
    expected_version: int | None = Field(default=None, ge=1)
    request_id: str | None = Field(default=None, max_length=64)


def _task_or_404(db: DBSession, task_id: str, user_id: int, *, correlation: str | None = None) -> TaskRecord:
    task = service.get(db, task_id, user_id)
    if task is None:
        raise problem(404, "TASK_UNAVAILABLE", "Task is unavailable.", correlation=correlation)
    return task


def _conflict(error: TaskConflict, *, correlation: str | None = None):
    code = str(error)
    status = 409 if code in {"TASK_VERSION_CONFLICT", "TASK_ALREADY_TERMINAL"} else 400
    safe_code = code if code in {"TASK_VERSION_CONFLICT", "TASK_ALREADY_TERMINAL", "TASK_NOT_RETRYABLE", "TASK_NOT_RETRYABLE_STATE", "TASK_RETRY_LIMIT_REACHED"} else "TASK_ACTION_REJECTED"
    raise problem(status, safe_code, "Task action was not accepted.", correlation=correlation)


def _task_stream_cursor(after_id: int, last_event_id: str | None, correlation: str) -> int:
    """Use the most advanced valid client cursor without exposing parser details."""
    if last_event_id is None:
        return after_id
    try:
        header_cursor = int(last_event_id)
    except (TypeError, ValueError) as exc:
        raise problem(
            400,
            "TASK_STREAM_CURSOR_INVALID",
            "Task stream cursor must be a non-negative integer.",
            correlation=correlation,
        ) from exc
    if header_cursor < 0:
        raise problem(
            400,
            "TASK_STREAM_CURSOR_INVALID",
            "Task stream cursor must be a non-negative integer.",
            correlation=correlation,
        )
    return max(after_id, header_cursor)


def _retry_with_execution(db: DBSession, task: TaskRecord) -> TaskRecord:
    retry = service.retry(db, task)
    try:
        if retry.source in {"training", "agent_runtime", "model_download", "download"}:
            return executor.launch_retry(db, retry)
    except RetryExecutionError as error:
        return executor.fail_dispatch(db, retry, error)
    return retry

@router.post("")
def create_task(req: TaskCreateRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = service.create(
        db, user_id=user.id, task_type=req.task_type, source=req.source, title=req.title,
        summary=req.summary, metadata=req.metadata, cancelable=req.cancelable,
        retryable=req.retryable, priority=req.priority, idempotency_key=req.idempotency_key,
    )
    task_outbox_publisher.nudge()
    return task.to_dict()


@router.get("/stream")
def stream_tasks(
    after_id: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: User = Depends(get_current_user),
):
    """Stream cursor-ordered task events with durable DB replay and heartbeats."""
    corr = correlation_id()
    cursor = _task_stream_cursor(after_id, last_event_id, corr)

    def event_generator():
        nonlocal cursor
        delivered = 0
        yield "retry: 1000\n\n"
        while True:
            db = SessionLocal()
            try:
                events = service.events_after(db, user.id, cursor, limit=_SSE_REPLAY_BATCH)
            finally:
                db.close()
            if events:
                for event in events:
                    cursor = event.id
                    delivered += 1
                    payload = event.to_dict()
                    import json
                    yield f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                    if delivered >= _SSE_MAX_EVENTS_PER_CONNECTION:
                        control = {
                            "after_id": cursor,
                            "code": "TASK_STREAM_RESYNC_REQUIRED",
                            "reason": "connection_batch_limit",
                            "correlation_id": corr,
                        }
                        yield f"event: resync_required\ndata: {json.dumps(control, separators=(',', ':'))}\n\n"
                        return
                continue
            # The outbox hub wakes early when a committed event becomes available.
            task_event_hub.wait_for_user(user.id, cursor, timeout=10.0)
            yield f": heartbeat {cursor}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": corr,
            "X-SSE-Cursor": str(cursor),
        },
    )


@router.get("")
def list_tasks(
    status: str | None = None, task_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0),
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    project_legacy_tasks(db, user.id)
    return {"tasks": [task.to_dict() for task in service.list(db, user.id, status=status, task_type=task_type, limit=limit, offset=offset)]}


@router.get("/summary")
def task_summary(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    project_legacy_tasks(db, user.id)
    return service.summary(db, user.id)


@router.get("/{task_id}")
def get_task(task_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return _task_or_404(db, task_id, user.id).to_dict()


@router.get("/{task_id}/events")
def task_events(task_id: str, limit: int = Query(default=200, ge=1, le=500), db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = _task_or_404(db, task_id, user.id)
    return {"events": [event.to_dict() for event in service.events(db, task, limit)]}


@router.post("/{task_id}/transition")
def transition_task(task_id: str, req: TaskTransitionRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = _task_or_404(db, task_id, user.id)
    try:
        task = service.transition(db, task, req.status, summary=req.summary, progress_current=req.progress_current,
            progress_total=req.progress_total, progress_unit=req.progress_unit, progress_percent=req.progress_percent,
            result=req.result, error_code=req.error_code, error_message=req.error_message,
            error_detail=req.error_detail, required_action=req.required_action, expected_version=req.expected_version)
    except TaskConflict as error:
        _conflict(error)
    task_outbox_publisher.nudge()
    return task.to_dict()


@router.post("/retry-batch")
def retry_tasks_batch(req: TaskBatchRetryRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "TASK_RETRY_CONFIRMATION_REQUIRED", "Confirm before retrying tasks.", correlation=corr)
    task_ids = list(dict.fromkeys(req.task_ids))
    audit_metadata = {"confirmed": True, "requested_count": len(task_ids), "accepted_count": 0, "rejected_count": 0}
    try:
        validate_control_plane_audit_metadata("task.retry_batch", audit_metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=corr) from exc
    succeeded = []
    failures = []
    for task_id in task_ids:
        task = service.get(db, task_id, user.id)
        if task is None:
            failures.append({"task_id": task_id, "code": "TASK_UNAVAILABLE", "message": "Task is unavailable."})
            continue
        expected_version = req.expected_versions.get(task_id)
        if expected_version is not None and task.version != expected_version:
            failures.append({"task_id": task_id, "code": "TASK_VERSION_CONFLICT", "message": "Task action was not accepted."})
            continue
        try:
            retry = _retry_with_execution(db, task)
            succeeded.append(retry.to_dict())
        except TaskConflict as error:
            failures.append({"task_id": task_id, "code": str(error), "message": "Task retry was not accepted."})
    task_outbox_publisher.nudge()
    audit_metadata.update(accepted_count=len(succeeded), rejected_count=len(failures))
    try:
        record_control_plane_operation(db, user_id=user.id, action="task.retry_batch", object_type="task_batch", object_id=f"count:{len(task_ids)}", correlation_id=corr, metadata=audit_metadata)
        commit_control_plane_audit(db)
    except (AuditMetadataRejected, AuditPersistenceError) as exc:
        raise problem(503, "TASK_RETRY_AUDIT_DURABILITY_UNKNOWN", "Task retry was accepted, but audit durability is unknown.", correlation=corr) from exc
    return operation_result({"tasks": succeeded, "failures": failures}, corr)

@router.post("/{task_id}/retry")
def retry_task(task_id: str, req: TaskActionRequest | None = None, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "TASK_RETRY_CONFIRMATION_REQUIRED", "Confirm before retrying a task.", correlation=corr)
    audit_metadata = {"confirmed": True}
    try:
        validate_control_plane_audit_metadata("task.retry", audit_metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=corr) from exc
    task = _task_or_404(db, task_id, user.id, correlation=corr)
    if req.expected_version is not None and task.version != req.expected_version:
        raise problem(409, "TASK_VERSION_CONFLICT", "Task action was not accepted.", correlation=corr)
    try:
        retry = _retry_with_execution(db, task)
    except TaskConflict as error:
        _conflict(error, correlation=corr)
    task_outbox_publisher.nudge()
    try:
        record_control_plane_operation(db, user_id=user.id, action="task.retry", object_type="task", object_id=retry.task_id, correlation_id=corr, metadata=audit_metadata)
        commit_control_plane_audit(db)
    except (AuditMetadataRejected, AuditPersistenceError) as exc:
        raise problem(503, "TASK_RETRY_AUDIT_DURABILITY_UNKNOWN", "Task retry was accepted, but audit durability is unknown.", correlation=corr) from exc
    return operation_result(retry.to_dict(), corr)


@router.get("/{task_id}/logs")
def task_logs(task_id: str, limit: int = Query(default=200, ge=1, le=500), db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = _task_or_404(db, task_id, user.id)
    return executor.logs(db, task, limit=limit)

@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, req: TaskActionRequest | None = None, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "TASK_CANCEL_CONFIRMATION_REQUIRED", "Confirm before cancelling a task.", correlation=corr)
    audit_metadata = {"confirmed": True}
    try:
        validate_control_plane_audit_metadata("task.cancel", audit_metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=corr) from exc
    task = _task_or_404(db, task_id, user.id, correlation=corr)
    if req.expected_version is not None and task.version != req.expected_version:
        raise problem(409, "TASK_VERSION_CONFLICT", "Task action was not accepted.", correlation=corr)
    try:
        task = service.request_cancel(db, task)
    except TaskConflict as error:
        _conflict(error, correlation=corr)
    task_outbox_publisher.nudge()
    try:
        record_control_plane_operation(db, user_id=user.id, action="task.cancel", object_type="task", object_id=task.task_id, correlation_id=corr, metadata=audit_metadata)
        commit_control_plane_audit(db)
    except (AuditMetadataRejected, AuditPersistenceError) as exc:
        raise problem(503, "TASK_CANCEL_AUDIT_DURABILITY_UNKNOWN", "Task cancellation was accepted, but audit durability is unknown.", correlation=corr) from exc
    return operation_result(task.to_dict(), corr)


@router.get("/onboarding/state")
def onboarding_state(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    ready_models = db.query(ModelRecord).filter(ModelRecord.status == "available").filter((ModelRecord.user_id == user.id) | (ModelRecord.user_id.is_(None))).count()
    has_session = db.query(ChatSession).filter_by(user_id=user.id).count() > 0
    has_run = db.query(AgentRun).filter_by(user_id=user.id).filter(AgentRun.status.in_(["COMPLETED", "SUCCEEDED"])).count() > 0
    next_step = "select_model" if not ready_models else ("send_message" if not has_session else ("run_agent" if not has_run else "complete"))
    return {
        "server_connected": True,
        "ready_model_count": ready_models,
        "has_sent_message": has_session,
        "has_completed_agent_run": has_run,
        "next_recommended_step": next_step,
        "is_complete": next_step == "complete",
    }
