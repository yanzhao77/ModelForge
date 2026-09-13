"""Runtime API routes."""

from core.api_contracts import correlation_id, problem
from core.security import get_runtime_admin
from fastapi import APIRouter, Depends, HTTPException
from models.records import User
from pydantic import BaseModel, Field
from services.resource_lease import (
    ResourceBusy,
    inference_holder,
    inference_lease,
    transient_hold,
)

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


@router.post("/start")
async def runtime_start(req: LoadRequest, _admin: User = Depends(get_runtime_admin)):
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
async def runtime_chat(req: ChatRequest, _admin: User = Depends(get_runtime_admin)):
    """Send a chat request to the loaded model."""
    corr = correlation_id()
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        with transient_hold(inference_lease, user_id=_admin.id, username=_admin.username):
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
async def runtime_stop(req: LoadRequest, _admin: User = Depends(get_runtime_admin)):
    """Stop/unload a model."""
    try:
        inference_lease.release(user_id=_admin.id)
    except ResourceBusy as exc:
        raise exc.to_problem() from exc
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
    return {**payload, "inference_holder": holder}
