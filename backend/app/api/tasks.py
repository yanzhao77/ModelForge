"""Global persisted task center and onboarding API routes."""
from __future__ import annotations

from core.database import SessionLocal, get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from models.records import AgentRun, ModelRecord, TaskRecord, User
from models.records import Session as ChatSession
from pydantic import BaseModel, Field
from services.task_execution import RetryExecutionError, TaskExecutionService
from services.task_realtime import task_event_hub, task_outbox_publisher
from services.task_service import TaskConflict, TaskService, project_legacy_tasks
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/tasks", tags=["tasks"])
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

def _task_or_404(db: DBSession, task_id: str, user_id: int) -> TaskRecord:
    task = service.get(db, task_id, user_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _conflict(error: TaskConflict):
    code = str(error)
    status = 409 if code in {"TASK_VERSION_CONFLICT", "TASK_ALREADY_TERMINAL"} else 400
    raise HTTPException(status_code=status, detail={"code": code, "message": "任务状态不允许该操作"})


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
    try:
        cursor = max(after_id, int(last_event_id or 0))
    except ValueError:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer cursor")

    def event_generator():
        nonlocal cursor
        while True:
            db = SessionLocal()
            try:
                events = service.events_after(db, user.id, cursor)
            finally:
                db.close()
            if events:
                for event in events:
                    cursor = event.id
                    payload = event.to_dict()
                    import json
                    yield f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                continue
            # The outbox hub wakes early when a committed event becomes available.
            task_event_hub.wait_for_user(user.id, cursor, timeout=10.0)
            yield f": heartbeat {cursor}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
    task_ids = list(dict.fromkeys(req.task_ids))
    succeeded = []
    failures = []
    for task_id in task_ids:
        task = service.get(db, task_id, user.id)
        if task is None:
            failures.append({"task_id": task_id, "code": "TASK_NOT_FOUND", "message": "任务不存在或不属于当前账号"})
            continue
        try:
            succeeded.append(_retry_with_execution(db, task).to_dict())
        except TaskConflict as error:
            failures.append({"task_id": task_id, "code": str(error), "message": "任务状态不允许重试"})
    task_outbox_publisher.nudge()
    return {"tasks": succeeded, "failures": failures}

@router.post("/{task_id}/retry")
def retry_task(task_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = _task_or_404(db, task_id, user.id)
    try:
        retry = _retry_with_execution(db, task)
    except TaskConflict as error:
        _conflict(error)
    task_outbox_publisher.nudge()
    return retry.to_dict()


@router.get("/{task_id}/logs")
def task_logs(task_id: str, limit: int = Query(default=200, ge=1, le=500), db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = _task_or_404(db, task_id, user.id)
    return executor.logs(db, task, limit=limit)

@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = _task_or_404(db, task_id, user.id)
    try:
        task = service.request_cancel(db, task)
    except TaskConflict as error:
        _conflict(error)
    task_outbox_publisher.nudge()
    return task.to_dict()


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
