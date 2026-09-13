"""Runtime API routes."""

from core.api_contracts import correlation_id, problem
from core.database import get_db
from core.security import get_runtime_admin
from fastapi import APIRouter, Depends, HTTPException
from models.records import ModelRecord, User
from pydantic import BaseModel, Field
from services.model_resolver import ModelResolver
from services.model_runtime_manager import ModelRuntimeError, get_model_runtime_manager
from services.resource_lease import (
    ResourceBusy,
    inference_holder,
    inference_lease,
    transient_hold,
)
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/runtime", tags=["runtime"])


class ChatMessage(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=32_000)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=256)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)


class LoadRequest(BaseModel):
    model: str = Field(min_length=1, max_length=256)


class RuntimeResponse(BaseModel):
    status: str
    model: str
    content: str = ""


# In-memory runtime reference (injected by app startup)
_runtime = None


def set_runtime(runtime):
    global _runtime
    _runtime = runtime


def _get_runtime():
    if _runtime is None:
        raise problem(503, "RUNTIME_UNAVAILABLE", "运行时当前不可用，请稍后重试。")
    return _runtime


def _registry_model(db: DBSession, user: User, reference: str) -> ModelRecord | None:
    """Resolve a request model to a registry record when one exists.

    Names that are not registered (for example an Ollama tag) fall through to
    the legacy runtime, so this stays backward compatible.
    """
    try:
        return ModelResolver(db).resolve(reference, user.id)
    except Exception:
        return None


def _runtime_problem(exc: ModelRuntimeError, corr: str):
    return problem(exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None)


@router.get("")
async def runtime_instance(_admin: User = Depends(get_runtime_admin)):
    """The single active local runtime instance (empty when idle)."""
    manager = get_model_runtime_manager()
    instance = manager.get_current()
    if instance is None:
        return {
            "active": False,
            "status": "idle",
            "instance_id": None,
            "model_id": None,
            "load_config": manager.load_config(),
            "recent_events": manager.recent_events(),
        }
    return {
        **instance.to_dict(),
        "load_config": manager.load_config(),
        "recent_events": manager.recent_events(),
    }


@router.post("/start")
async def runtime_start(
    req: LoadRequest,
    db: DBSession = Depends(get_db),
    _admin: User = Depends(get_runtime_admin),
):
    """Load a model into the runtime.

    The account keeps the inference lease only after a successful load: a
    failed load (runtime offline, model missing, load error) used to leave the
    lease held forever, which returned 409 RUNTIME_BUSY to every other account
    even though nothing was running.
    """
    # Only one account may hold the inference runtime at a time.
    corr = correlation_id()
    try:
        handle = inference_lease.acquire(user_id=_admin.id, username=_admin.username)
    except ResourceBusy as exc:
        raise exc.to_problem(corr) from exc
    record = _registry_model(db, _admin, req.model)
    if record is not None:
        try:
            instance = await get_model_runtime_manager().load(record.id, _admin.id, db=db)
        except ModelRuntimeError as exc:
            if handle.created:
                handle.release()
            raise _runtime_problem(exc, corr) from exc
        return {**instance.to_dict(), "model": instance.model_name, "content": ""}
    try:
        return await _get_runtime().load(req.model)
    except HTTPException as exc:
        if handle.created:
            handle.release()
        if isinstance(exc.detail, dict):
            raise
        raise problem(
            exc.status_code,
            "RUNTIME_UNAVAILABLE",
            "运行时当前不可用，请稍后重试。",
            correlation=corr,
        ) from exc
    except Exception as exc:
        if handle.created:
            handle.release()
        raise problem(
            502,
            "MODEL_LOAD_FAILED",
            "模型加载失败，请确认本地运行时可用或该模型已安装。",
            correlation=corr,
        ) from exc


@router.post("/chat")
async def runtime_chat(
    req: ChatRequest,
    db: DBSession = Depends(get_db),
    _admin: User = Depends(get_runtime_admin),
):
    """Send a chat request to the loaded model."""
    corr = correlation_id()
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    record = _registry_model(db, _admin, req.model)
    try:
        with transient_hold(inference_lease, user_id=_admin.id, username=_admin.username):
            if record is not None:
                try:
                    return await get_model_runtime_manager().chat(
                        record.id, messages, user_id=_admin.id, db=db
                    )
                except ModelRuntimeError as exc:
                    raise _runtime_problem(exc, corr) from exc
            return await _get_runtime().chat(req.model, messages)
    except ResourceBusy as exc:
        raise exc.to_problem(corr) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise problem(
            502,
            "INFERENCE_FAILED",
            "推理请求失败。请稍后重试。",
            correlation=corr,
        ) from exc


@router.post("/stop")
async def runtime_stop(
    req: LoadRequest,
    db: DBSession = Depends(get_db),
    _admin: User = Depends(get_runtime_admin),
):
    """Stop/unload a model."""
    try:
        inference_lease.release(user_id=_admin.id)
    except ResourceBusy as exc:
        raise exc.to_problem() from exc
    record = _registry_model(db, _admin, req.model)
    current = get_model_runtime_manager().get_current()
    if record is not None and current is not None and current.model_id == record.id:
        try:
            return await get_model_runtime_manager().unload(record.id, _admin.id, db=db)
        except ModelRuntimeError as exc:
            raise _runtime_problem(exc, correlation_id()) from exc
    return await _get_runtime().stop(req.model)


@router.get("/status")
async def runtime_status(_admin: User = Depends(get_runtime_admin)):
    """Runtime registry status."""
    runtime = _get_runtime()
    holder = inference_holder()
    if hasattr(runtime, "status"):
        payload = runtime.status()
    else:
        payload = {"default": "unknown", "runtimes": {}}
    manager = get_model_runtime_manager()
    instance = manager.get_current()
    return {
        **payload,
        "inference_holder": holder,
        "active": instance is not None,
        "instance": instance.to_dict() if instance is not None else None,
        "load_config": manager.load_config(),
        "recent_events": manager.recent_events(),
    }
