"""OpenAI-compatible /v1/chat/completions endpoint."""
import json
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.runtime_registry import get_runtime

router = APIRouter(tags=["openai"])


class OpenAIMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "default-model"
    messages: List[OpenAIMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048
    stream: Optional[bool] = False


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
        }
    }


@router.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        runtime = get_runtime()
        if req.stream:
            async def gen():
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
            return StreamingResponse(gen(), media_type="text/event-stream")
        result = await runtime.chat(
            req.model, messages,
            temperature=req.temperature, max_tokens=req.max_tokens,
        )
        return _openai_response(req.model, result.get("content", ""))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"推理失败: {e}")


@router.get("/v1/models")
async def list_openai_models():
    """OpenAI-compatible model list."""
    return {
        "object": "list",
        "data": [{"id": "default-model", "object": "model", "owned_by": "modelforge"}]
    }