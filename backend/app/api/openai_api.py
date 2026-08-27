"""OpenAI-compatible /v1/chat/completions endpoint."""
import json
import time
import uuid

from core.api_contracts import correlation_id
from core.security import get_current_user
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from models.records import User
from pydantic import BaseModel
from services.runtime_registry import get_runtime

router = APIRouter(tags=["openai"])


class OpenAIMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "default-model"
    messages: list[OpenAIMessage]
    temperature: float | None = 0.7
    max_tokens: int | None = 2048
    stream: bool | None = False


def _openai_response(model: str, content: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": len(content.split()),
            "total_tokens": len(content.split()),
        },
    }


def _openai_error(code: str, message: str, correlation: str) -> dict:
    """Return an OpenAI-compatible, content-free error envelope."""
    return {
        "error": {
            "message": message,
            "type": "server_error",
            "code": code,
            "param": None,
        },
        "correlation_id": correlation,
    }


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    user: User = Depends(get_current_user),
):
    """Proxy a user-authorized model request without exposing runtime errors."""
    del user  # Authentication dependency remains required; no identity is echoed.
    correlation = (request_id or correlation_id())[:64]
    messages = [{"role": message.role, "content": message.content} for message in req.messages]
    if req.stream:
        async def gen():
            try:
                runtime = get_runtime()
                runtime_obj = runtime.get()
                stream_fn = getattr(runtime_obj, "stream_chat", None)
                if stream_fn is not None:
                    async for chunk in stream_fn(req.model, messages):
                        event = {"choices": [{"delta": {"content": chunk}, "index": 0}]}
                        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                else:
                    result = await runtime.chat(req.model, messages)
                    content = result.get("content", "")
                    event = {"choices": [{"delta": {"content": content}, "index": 0}]}
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                event = _openai_error("INFERENCE_FAILED", "Inference request failed.", correlation)
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"X-Request-ID": correlation},
        )
    try:
        result = await get_runtime().chat(
            req.model,
            messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        return JSONResponse(
            _openai_response(req.model, result.get("content", "")),
            headers={"X-Request-ID": correlation},
        )
    except Exception:
        return JSONResponse(
            _openai_error("INFERENCE_FAILED", "Inference request failed.", correlation),
            status_code=500,
            headers={"X-Request-ID": correlation},
        )


@router.get("/v1/models")
async def list_openai_models(user: User = Depends(get_current_user)):
    """OpenAI-compatible model list."""
    del user  # Authentication dependency remains required; no identity is echoed.
    return {
        "object": "list",
        "data": [{"id": "default-model", "object": "model", "owned_by": "modelforge"}],
    }
