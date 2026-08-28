"""Runtime API routes."""

from core.security import get_runtime_admin
from fastapi import APIRouter, Depends, HTTPException
from models.records import User
from pydantic import BaseModel, Field

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
        raise HTTPException(status_code=503, detail="Runtime not initialized")
    return _runtime


@router.post("/start")
async def runtime_start(req: LoadRequest, _admin: User = Depends(get_runtime_admin)):
    """Load a model into the runtime."""
    return await _get_runtime().load(req.model)


@router.post("/chat")
async def runtime_chat(req: ChatRequest, _admin: User = Depends(get_runtime_admin)):
    """Send a chat request to the loaded model."""
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    return await _get_runtime().chat(req.model, messages)


@router.post("/stop")
async def runtime_stop(req: LoadRequest, _admin: User = Depends(get_runtime_admin)):
    """Stop/unload a model."""
    return await _get_runtime().stop(req.model)


@router.get("/status")
async def runtime_status(_admin: User = Depends(get_runtime_admin)):
    """Runtime registry status."""
    runtime = _get_runtime()
    if hasattr(runtime, "status"):
        return runtime.status()
    return {"default": "unknown", "runtimes": {}}