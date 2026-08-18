"""Runtime API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/runtime", tags=["runtime"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]


class LoadRequest(BaseModel):
    model: str


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
async def runtime_start(req: LoadRequest):
    """Load a model into the runtime."""
    return await _get_runtime().load(req.model)


@router.post("/chat")
async def runtime_chat(req: ChatRequest):
    """Send a chat request to the loaded model."""
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    return await _get_runtime().chat(req.model, messages)


@router.post("/stop")
async def runtime_stop(req: LoadRequest):
    """Stop/unload a model."""
    return await _get_runtime().stop(req.model)


@router.get("/status")
async def runtime_status():
    """Runtime registry status."""
    runtime = _get_runtime()
    if hasattr(runtime, "status"):
        return runtime.status()
    return {"default": "unknown", "runtimes": {}}