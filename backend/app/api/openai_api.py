"""OpenAI-compatible /v1/chat/completions endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from core.api_contracts import correlation_id
from core.openai_rate_limiter import (
    Lease,
    acquire_lease,
    check_and_record_rate_limit,
    inference_timeout_seconds,
    make_concurrency_response,
    make_timeout_response,
    maybe_cleanup_idle,
)
from core.security import get_current_user
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from models.records import User
from pydantic import BaseModel, Field
from services.runtime_registry import get_runtime

log = logging.getLogger(__name__)

router = APIRouter(tags=["openai"])

_MAX_MESSAGE_COUNT = 100
_MAX_SINGLE_CONTENT_LENGTH = 200000
_MAX_TOTAL_PROMPT_CHARS = 1000000


class OpenAIMessage(BaseModel):
    role: str = Field(pattern="^(system|developer|user|assistant)$")
    content: str = Field(min_length=1, max_length=_MAX_SINGLE_CONTENT_LENGTH)


class ChatCompletionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255, default="default-model")
    messages: list[OpenAIMessage] = Field(min_length=1, max_length=_MAX_MESSAGE_COUNT)
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=2048, ge=1, le=32768)
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


async def _safe_aclose(iterator: AsyncIterator[object]) -> None:
    """Safely close an async iterator if it supports aclose()."""
    aclose = getattr(iterator, "aclose", None)
    if aclose is not None:
        try:
            await aclose()
        except Exception:
            pass


async def _timed_next(ait: AsyncIterator[object], remaining: float) -> object:
    """Get the next item from an async iterator with a timeout."""
    return await asyncio.wait_for(ait.__anext__(), timeout=remaining)


async def _stream_with_lease(
    lease: Lease,
    model: str,
    messages: list[dict],
    correlation: str,
    total_timeout: float,
) -> AsyncIterator[str]:
    """Streaming generator that owns its lease for the full stream lifetime.

    The lease is released exactly once in the finally block, regardless of
    how the generator terminates (normal [DONE], exception, timeout, or
    client disconnect / task cancellation).

    Total deadline: ``total_timeout`` seconds from now.  Each iterator
    advancement also respects the remaining time.
    """
    deadline = asyncio.get_event_loop().time() + total_timeout
    try:
        runtime = get_runtime()
        runtime_obj = runtime.get()
        stream_fn = getattr(runtime_obj, "stream_chat", None)
        if stream_fn is not None:
            ait = stream_fn(model, messages)
            try:
                while True:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        event = _openai_error("REQUEST_TIMEOUT", "Inference request timed out.", correlation)
                        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk = await _timed_next(ait, remaining)
                    except StopAsyncIteration:
                        break
                    event = {"choices": [{"delta": {"content": chunk}, "index": 0}]}
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            except asyncio.CancelledError:
                await _safe_aclose(ait)
                raise
            except Exception:
                await _safe_aclose(ait)
                raise
            finally:
                await _safe_aclose(ait)
        else:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                event = _openai_error("REQUEST_TIMEOUT", "Inference request timed out.", correlation)
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"
                return
            result = await asyncio.wait_for(
                runtime.chat(model, messages),
                timeout=remaining,
            )
            content = result.get("content", "")
            evt = {"choices": [{"delta": {"content": content}, "index": 0}]}
            yield "data: " + json.dumps(evt, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        event = _openai_error("REQUEST_TIMEOUT", "Inference request timed out.", correlation)
        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    except Exception:
        event = _openai_error("INFERENCE_FAILED", "Inference request failed.", correlation)
        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    finally:
        lease.release()
        maybe_cleanup_idle()


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    user: User = Depends(get_current_user),
):
    """Proxy a user-authorized model request without exposing runtime errors."""
    correlation = (request_id or correlation_id())[:64]

    # --- Rate limit check (atomic check + record) ---
    rate_resp = await check_and_record_rate_limit(user.id)
    if rate_resp is not None:
        rate_resp.headers["X-Request-ID"] = correlation
        rate_resp.headers["X-Correlation-ID"] = correlation
        return rate_resp

    # --- Input validation (before concurrency gate) ---
    total_chars = sum(len(m.content) for m in req.messages)
    if total_chars > _MAX_TOTAL_PROMPT_CHARS:
        return JSONResponse(
            _openai_error("REQUEST_INVALID", f"Total prompt content exceeds {_MAX_TOTAL_PROMPT_CHARS} characters.", correlation),
            status_code=422,
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )

    messages = [{"role": message.role, "content": message.content} for message in req.messages]
    total_timeout = float(inference_timeout_seconds())

    # --- Per-user concurrency gate ---
    lease_or_err = await acquire_lease(user.id)
    if isinstance(lease_or_err, JSONResponse):
        lease_or_err.headers["X-Request-ID"] = correlation
        lease_or_err.headers["X-Correlation-ID"] = correlation
        return lease_or_err
    lease: Lease = lease_or_err

    if req.stream:
        # Streaming: the generator owns the lease for the full stream lifetime.
        # The outer try/finally must NOT release the lease.
        return StreamingResponse(
            _stream_with_lease(lease, req.model, messages, correlation, total_timeout),
            media_type="text/event-stream",
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )

    # Non-streaming: lease is released in the finally block below.
    try:
        result = await asyncio.wait_for(
            get_runtime().chat(
                req.model,
                messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            ),
            timeout=total_timeout,
        )
        resp = JSONResponse(
            _openai_response(req.model, result.get("content", "")),
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )
        return resp
    except asyncio.TimeoutError:
        resp = make_timeout_response(correlation)
        resp.headers["X-Request-ID"] = correlation
        resp.headers["X-Correlation-ID"] = correlation
        return resp
    except asyncio.CancelledError:
        raise
    except Exception:
        resp = JSONResponse(
            _openai_error("INFERENCE_FAILED", "Inference request failed.", correlation),
            status_code=500,
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )
        return resp
    finally:
        lease.release()
        maybe_cleanup_idle()


@router.get("/v1/models")
async def list_openai_models(user: User = Depends(get_current_user)):
    """OpenAI-compatible model list."""
    del user  # Authentication dependency remains required; no identity is echoed.
    return {
        "object": "list",
        "data": [{"id": "default-model", "object": "model", "owned_by": "modelforge"}],
    }
