"""Runtime API routes."""
from typing import List, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/runtime", tags=["runtime"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]


class LoadRequest(BaseModel):
    model: str


class RuntimeResponse(BaseModel):
    status: str
    model: str
    content: str = ""


# In-memory runtime reference (injected by app startup)
_ollama_runtime = None


def set_runtime(runtime):
    global _ollama_runtime
    _ollama_runtime = runtime


@router.post("/start")
async def runtime_start(req: LoadRequest):
    """Load a model into the runtime."""
    if _ollama_runtime is None:
        raise HTTPException(status_code=503, detail="Runtime not initialized")
    return await _ollama_runtime.load(req.model)


@router.post("/chat")
async def runtime_chat(req: ChatRequest):
    """Send a chat request to the loaded model."""
    if _ollama_runtime is None:
        raise HTTPException(status_code=503, detail="Runtime not initialized")
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    return await _ollama_runtime.chat(req.model, messages)


@router.post("/stop")
async def runtime_stop(req: LoadRequest):
    """Stop/unload a model."""
    if _ollama_runtime is None:
        raise HTTPException(status_code=503, detail="Runtime not initialized")
    return await _ollama_runtime.stop(req.model)
