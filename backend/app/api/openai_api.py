"""OpenAI-compatible /v1/chat/completions endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

from core.api_contracts import correlation_id
from core.database import get_db
from core.openai_rate_limiter import (
    Lease,
    acquire_lease,
    check_and_record_rate_limit,
    inference_timeout_seconds,
    make_concurrency_response,
    make_timeout_response,
    maybe_cleanup_idle,
)
from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from services.local_api_service import (
    SCOPE_AUDIO,
    SCOPE_CHAT,
    SCOPE_IMAGES,
    SCOPE_MODELS_READ,
    SCOPE_RESPONSES,
    LocalApiError,
    LocalApiPrincipal,
    LocalApiService,
    authenticate_local_api_key,
    openai_error_payload,
)
from services.model_capabilities import ModelCapability
from services.model_capability_registry import probed_video_models
from services.model_runtime_manager import get_model_runtime_manager
from services.resource_lease import ResourceBusy, inference_lease
from services.runtime_registry import get_runtime
from sqlalchemy.orm import Session as DBSession

log = logging.getLogger(__name__)

router = APIRouter(tags=["openai"])

_MAX_MESSAGE_COUNT = 100
_MAX_SINGLE_CONTENT_LENGTH = 200000
_MAX_TOTAL_PROMPT_CHARS = 1000000


class OpenAIMessage(BaseModel):
    role: str = Field(pattern="^(system|developer|user|assistant)$")
    content: str | list[dict[str, Any]] = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255, default="default-model")
    messages: list[OpenAIMessage] = Field(min_length=1, max_length=_MAX_MESSAGE_COUNT)
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=2048, ge=1, le=32768)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=32768)
    stop: str | list[str] | None = None
    seed: int | None = None
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    stream: bool | None = False


class ResponsesRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255, default="default-model")
    input: str | list[dict[str, Any]] = Field(min_length=1)
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_output_tokens: int | None = Field(default=2048, ge=1, le=32768)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    stop: str | list[str] | None = None
    seed: int | None = None
    stream: bool | None = False


class ImageGenerationRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1, max_length=4000)
    size: str | None = Field(default="1024x1024", max_length=32)
    n: int | None = Field(default=1, ge=1, le=10)


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


def _auth(db: DBSession, authorization: str | None, scope: str) -> LocalApiPrincipal | JSONResponse:
    try:
        return authenticate_local_api_key(db, authorization, required_scope=scope)
    except LocalApiError as exc:
        corr = correlation_id()[:64]
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, corr, param=exc.param),
            status_code=exc.status_code,
            headers={"X-Request-ID": corr, "X-Correlation-ID": corr},
        )


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
    inference_handle=None,
    runtime=None,
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
        # ``runtime`` is only supplied when the request resolved to a registry
        # model; otherwise the legacy per-backend registry is used, which keeps
        # the standalone streaming-lease tests (and Ollama deployments) intact.
        runtime = runtime or get_runtime()
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
        if inference_handle is not None and inference_handle.created:
            inference_handle.release()
        lease.release()
        maybe_cleanup_idle()


class _RegistryEngine:
    """Legacy runtime-engine surface over the unified runtime manager."""

    def __init__(self, model_id: int, user_id: int):
        self._model_id = model_id
        self._user_id = user_id

    @staticmethod
    def _translate(kwargs: dict) -> dict:
        options = {key: value for key, value in kwargs.items() if value is not None}
        if "max_tokens" in options:
            options.setdefault("max_new_tokens", options.pop("max_tokens"))
        return options

    async def chat(self, model: str, messages: list, **kwargs) -> dict:
        return await get_model_runtime_manager().chat(
            self._model_id, messages, user_id=self._user_id, **self._translate(kwargs)
        )

    def stream_chat(self, model: str, messages: list, **kwargs):
        return get_model_runtime_manager().stream_chat(
            self._model_id, messages, user_id=self._user_id, **self._translate(kwargs)
        )


class _RegistryRuntime:
    """Adapts the runtime manager to the ``runtime.get()`` contract."""

    def __init__(self, model_id: int, user_id: int):
        self._engine = _RegistryEngine(model_id, user_id)

    def get(self, name: str | None = None):  # noqa: ARG002 - legacy signature
        return self._engine

    async def chat(self, model: str, messages: list, **kwargs) -> dict:
        return await self._engine.chat(model, messages, **kwargs)


def _registry_runtime(db: DBSession, user_id: int, model_name: str):
    """Return a manager-backed runtime when ``model_name`` is a known model."""
    record = LocalApiService(db).resolve_model(user_id, model_name)
    if record is None:
        return None
    return _RegistryRuntime(record.id, user_id)


def _is_blocked_host(hostname: str | None) -> bool:
    if not hostname:
        return True
    host = hostname.lower().strip("[]")
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local")


def _validate_image_reference(ref: str, correlation: str) -> None:
    if ref.startswith("data:"):
        header = ref.split(",", 1)[0].lower()
        if not any(header.startswith(f"data:{mime};base64") for mime in ("image/png", "image/jpeg", "image/webp", "image/gif")):
            raise LocalApiError(422, "IMAGE_MIME_UNSUPPORTED", "Image Data URLs must be png, jpeg, webp, or gif.", param="messages")
        if len(ref) > 12_000_000:
            raise LocalApiError(413, "IMAGE_TOO_LARGE", "Image Data URL exceeds the local API size limit.", param="messages")
        return
    parsed = urlparse(ref)
    if parsed.scheme not in {"http", "https"}:
        raise LocalApiError(422, "IMAGE_URL_UNSUPPORTED", "Image URLs must use http, https, or a supported Data URL.", param="messages")
    if _is_blocked_host(parsed.hostname):
        raise LocalApiError(422, "IMAGE_URL_BLOCKED", "Image URLs cannot target localhost or local network names.", param="messages")
    del correlation


def _normalise_message_content(content: str | list[dict[str, Any]], correlation: str) -> tuple[str, bool]:
    if isinstance(content, str):
        if len(content) > _MAX_SINGLE_CONTENT_LENGTH:
            raise LocalApiError(422, "REQUEST_INVALID", "message content is too large.", param="messages")
        return content, False
    text_parts: list[str] = []
    image_count = 0
    for part in content:
        part_type = str(part.get("type") or "")
        if part_type in {"text", "input_text"}:
            text = str(part.get("text") or "")
            if text:
                text_parts.append(text)
        elif part_type in {"image_url", "input_image"}:
            image_count += 1
            image_url = part.get("image_url")
            ref = image_url.get("url") if isinstance(image_url, dict) else part.get("image_url") or part.get("url")
            _validate_image_reference(str(ref or ""), correlation)
        else:
            raise LocalApiError(422, "MESSAGE_PART_UNSUPPORTED", f"Unsupported message content part type: {part_type or 'unknown'}.", param="messages")
    if image_count > 8:
        raise LocalApiError(413, "TOO_MANY_IMAGES", "At most 8 images are accepted per request.", param="messages")
    text = "\n".join(text_parts).strip()
    if not text and image_count:
        text = "[image input]"
    if len(text) > _MAX_SINGLE_CONTENT_LENGTH:
        raise LocalApiError(422, "REQUEST_INVALID", "message content is too large.", param="messages")
    return text, image_count > 0


def _messages_from_chat(messages: list[OpenAIMessage], correlation: str) -> tuple[list[dict], bool]:
    normalised: list[dict] = []
    has_images = False
    for message in messages:
        content, message_has_images = _normalise_message_content(message.content, correlation)
        has_images = has_images or message_has_images
        normalised.append({"role": message.role, "content": content})
    return normalised, has_images


def _messages_from_responses_input(value: str | list[dict[str, Any]], correlation: str) -> tuple[list[dict], bool]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}], False
    messages: list[dict] = []
    has_images = False
    for item in value:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")
        content = item.get("content")
        if isinstance(content, str) and content:
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            text, item_has_images = _normalise_message_content(content, correlation)
            has_images = has_images or item_has_images
            messages.append({"role": role, "content": text})
    if not messages:
        raise LocalApiError(422, "REQUEST_INVALID", "input must contain text content.", param="input")
    return messages, has_images


def _responses_payload(model: str, content: str) -> dict:
    return {
        "id": f"resp-{uuid.uuid4().hex[:16]}",
        "object": "response",
        "created_at": int(time.time()),
        "model": model,
        "output": [
            {
                "id": f"msg-{uuid.uuid4().hex[:12]}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        ],
        "output_text": content,
        "usage": {
            "input_tokens": 0,
            "output_tokens": len(content.split()),
            "total_tokens": len(content.split()),
        },
    }


async def _responses_stream_with_lease(
    lease: Lease,
    model: str,
    messages: list[dict],
    correlation: str,
    total_timeout: float,
    inference_handle=None,
    runtime=None,
) -> AsyncIterator[str]:
    response_id = f"resp-{uuid.uuid4().hex[:16]}"
    yield "data: " + json.dumps({"type": "response.created", "response": {"id": response_id, "object": "response", "created_at": int(time.time()), "model": model}}, ensure_ascii=False) + "\n\n"
    async for event in _stream_with_lease(lease, model, messages, correlation, total_timeout, inference_handle, runtime=runtime):
        if event.strip() == "data: [DONE]":
            yield "data: " + json.dumps({"type": "response.completed", "response": {"id": response_id, "model": model}}, ensure_ascii=False) + "\n\n"
            yield event
            return
        if not event.startswith("data: "):
            yield event
            continue
        try:
            payload = json.loads(event.removeprefix("data: ").strip())
        except ValueError:
            yield event
            continue
        if "error" in payload:
            yield "data: " + json.dumps({"type": "error", **payload}, ensure_ascii=False) + "\n\n"
            continue
        delta = "".join(
            str(choice.get("delta", {}).get("content") or "")
            for choice in payload.get("choices", [])
            if isinstance(choice, dict)
        )
        if delta:
            yield "data: " + json.dumps({"type": "response.output_text.delta", "delta": delta, "response_id": response_id}, ensure_ascii=False) + "\n\n"


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    """Proxy a user-authorized model request without exposing runtime errors."""
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, SCOPE_CHAT)
    if isinstance(principal, JSONResponse):
        return principal
    started = time.monotonic()
    service = LocalApiService(db)

    # --- Rate limit check (atomic check + record) ---
    rate_resp = await check_and_record_rate_limit(principal.user_id)
    if rate_resp is not None:
        rate_resp.headers["X-Request-ID"] = correlation
        rate_resp.headers["X-Correlation-ID"] = correlation
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/chat/completions",
            method=request.method,
            model=req.model,
            status_code=rate_resp.status_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="RATE_LIMITED",
        )
        return rate_resp

    # --- Input validation (before concurrency gate) ---
    try:
        messages, has_images = _messages_from_chat(req.messages, correlation)
    except LocalApiError as exc:
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, correlation, param=exc.param),
            status_code=exc.status_code,
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )
    total_chars = sum(len(m["content"]) for m in messages)
    if total_chars > _MAX_TOTAL_PROMPT_CHARS:
        return JSONResponse(
            _openai_error("REQUEST_INVALID", f"Total prompt content exceeds {_MAX_TOTAL_PROMPT_CHARS} characters.", correlation),
            status_code=422,
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )

    total_timeout = float(inference_timeout_seconds())
    try:
        required_capability = ModelCapability.VISION.value if has_images else ModelCapability.INFERENCE.value
        record = service.require_model(principal.user_id, req.model, capability=required_capability)
        service.require_loaded_or_autoload(principal.user_id, record)
    except LocalApiError as exc:
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/chat/completions",
            method=request.method,
            model=req.model,
            status_code=exc.status_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code=exc.code,
        )
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, correlation, param=exc.param),
            status_code=exc.status_code,
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )
    runtime = _RegistryRuntime(record.id, principal.user_id)

    # --- Exclusive inference gate: one account at a time ---
    try:
        inference_handle = inference_lease.acquire(user_id=principal.user_id, username=f"api:{principal.key_prefix}")
    except ResourceBusy as exc:
        busy = exc.to_problem(correlation)
        return JSONResponse(
            _openai_error(exc.lease.code, busy.detail["message"], correlation),
            status_code=409,
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )

    # --- Per-user concurrency gate ---
    lease_or_err = await acquire_lease(principal.user_id)
    if isinstance(lease_or_err, JSONResponse):
        if inference_handle.created:
            inference_handle.release()
        lease_or_err.headers["X-Request-ID"] = correlation
        lease_or_err.headers["X-Correlation-ID"] = correlation
        return lease_or_err
    lease: Lease = lease_or_err

    if req.stream:
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/chat/completions",
            method=request.method,
            model=req.model,
            status_code=200,
            duration_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=sum(len(message["content"].split()) for message in messages),
        )
        # Streaming: the generator owns the lease for the full stream lifetime.
        # The outer try/finally must NOT release the lease.
        return StreamingResponse(
            _stream_with_lease(lease, req.model, messages, correlation, total_timeout, inference_handle, runtime=runtime),
            media_type="text/event-stream",
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )

    # Non-streaming: lease is released in the finally block below.
    try:
        result = await asyncio.wait_for(
            (runtime or get_runtime()).chat(
                req.model,
                messages,
                temperature=req.temperature,
                top_p=req.top_p,
                max_tokens=req.max_completion_tokens or req.max_tokens,
                stop=req.stop,
                seed=req.seed,
                frequency_penalty=req.frequency_penalty,
                presence_penalty=req.presence_penalty,
            ),
            timeout=total_timeout,
        )
        resp = JSONResponse(
            _openai_response(req.model, result.get("content", "")),
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/chat/completions",
            method=request.method,
            model=req.model,
            status_code=200,
            duration_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=sum(len(message["content"].split()) for message in messages),
            completion_tokens=len(str(result.get("content", "")).split()),
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
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/chat/completions",
            method=request.method,
            model=req.model,
            status_code=500,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="INFERENCE_FAILED",
        )
        return resp
    finally:
        if inference_handle.created:
            inference_handle.release()
        lease.release()
        maybe_cleanup_idle()


@router.get("/v1/models")
async def list_openai_models(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    """OpenAI-compatible model list sourced from registry and video runtimes."""
    principal = _auth(db, authorization, SCOPE_MODELS_READ)
    if isinstance(principal, JSONResponse):
        return principal
    data = LocalApiService(db).list_model_descriptors(principal.user_id)
    for model in await probed_video_models():
        data.append(
            {
                "id": model.model_id,
                "object": "model",
                "owned_by": "local",
                "modelforge": {
                    "contract": "modelforge.video.v1",
                    "capabilities": ["video_generation"],
                    "readiness": model.readiness,
                    "readiness_reason": model.readiness_reason,
                    "runtime": model.runtime_name,
                    "upstream_id": model.upstream_id,
                    "experimental": model.experimental,
                    "profiles": [
                        {
                            "id": profile.profile_id,
                            "seconds": profile.seconds,
                            "fps": profile.fps,
                            "size": profile.size,
                            "frames": profile.frames,
                            "default_steps": profile.default_steps,
                        }
                        for profile in model.profiles
                    ],
                },
            }
        )
    if not data:
        # Preserve the historical placeholder so an empty install still answers
        # with a valid OpenAI model list.
        data = [{"id": "default-model", "object": "model", "owned_by": "modelforge"}]
    return {"object": "list", "data": data}


@router.get("/v1/models/{model}")
async def get_openai_model(
    model: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    principal = _auth(db, authorization, SCOPE_MODELS_READ)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        record = LocalApiService(db).require_model(principal.user_id, model)
    except LocalApiError as exc:
        corr = correlation_id()[:64]
        return JSONResponse(openai_error_payload(exc.code, exc.message, corr, param=exc.param), status_code=exc.status_code, headers={"X-Request-ID": corr, "X-Correlation-ID": corr})
    return LocalApiService(db).model_descriptor(principal.user_id, record)


@router.post("/v1/responses")
async def responses(
    req: ResponsesRequest,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, SCOPE_RESPONSES)
    if isinstance(principal, JSONResponse):
        return principal
    started = time.monotonic()
    service = LocalApiService(db)
    try:
        messages, has_images = _messages_from_responses_input(req.input, correlation)
        required_capability = ModelCapability.VISION.value if has_images else ModelCapability.INFERENCE.value
        record = service.require_model(principal.user_id, req.model, capability=required_capability)
        service.require_loaded_or_autoload(principal.user_id, record)
    except LocalApiError as exc:
        return JSONResponse(openai_error_payload(exc.code, exc.message, correlation, param=exc.param), status_code=exc.status_code, headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation})
    runtime = _RegistryRuntime(record.id, principal.user_id)
    if req.stream:
        try:
            inference_handle = inference_lease.acquire(user_id=principal.user_id, username=f"api:{principal.key_prefix}")
        except ResourceBusy as exc:
            busy = exc.to_problem(correlation)
            return JSONResponse(_openai_error(exc.lease.code, busy.detail["message"], correlation), status_code=409, headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation})
        lease_or_err = await acquire_lease(principal.user_id)
        if isinstance(lease_or_err, JSONResponse):
            if inference_handle.created:
                inference_handle.release()
            lease_or_err.headers["X-Request-ID"] = correlation
            lease_or_err.headers["X-Correlation-ID"] = correlation
            return lease_or_err
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/responses",
            method=request.method,
            model=req.model,
            status_code=200,
            duration_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=sum(len(item["content"].split()) for item in messages),
        )
        return StreamingResponse(
            _responses_stream_with_lease(lease_or_err, req.model, messages, correlation, float(inference_timeout_seconds()), inference_handle, runtime=runtime),
            media_type="text/event-stream",
            headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
        )
    try:
        result = await asyncio.wait_for(
            runtime.chat(
                req.model,
                messages,
                temperature=req.temperature,
                top_p=req.top_p,
                max_tokens=req.max_tokens or req.max_output_tokens,
                stop=req.stop,
                seed=req.seed,
            ),
            timeout=float(inference_timeout_seconds()),
        )
        content = str(result.get("content") or "")
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/responses",
            method=request.method,
            model=req.model,
            status_code=200,
            duration_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=sum(len(item["content"].split()) for item in messages),
            completion_tokens=len(content.split()),
        )
        return JSONResponse(_responses_payload(req.model, content), headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation})
    except Exception:
        service.record_request(
            principal,
            request_id=correlation,
            endpoint="/v1/responses",
            method=request.method,
            model=req.model,
            status_code=500,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="INFERENCE_FAILED",
        )
        return JSONResponse(_openai_error("INFERENCE_FAILED", "Inference request failed.", correlation), status_code=500, headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation})


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    model: str = Form(...),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    del file
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, SCOPE_AUDIO)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        LocalApiService(db).require_model(principal.user_id, model, capability=ModelCapability.AUDIO.value)
    except LocalApiError as exc:
        return JSONResponse(openai_error_payload(exc.code, exc.message, correlation, param=exc.param), status_code=exc.status_code, headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation})
    return JSONResponse(
        openai_error_payload("AUDIO_BACKEND_UNAVAILABLE", "Audio transcription runtime is not connected in this build.", correlation, param="model"),
        status_code=503,
        headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
    )


@router.post("/v1/images/generations")
async def image_generations(
    req: ImageGenerationRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, SCOPE_IMAGES)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        LocalApiService(db).require_model(principal.user_id, req.model, capability=ModelCapability.IMAGE.value)
    except LocalApiError as exc:
        return JSONResponse(openai_error_payload(exc.code, exc.message, correlation, param=exc.param), status_code=exc.status_code, headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation})
    return JSONResponse(
        openai_error_payload("IMAGE_BACKEND_UNAVAILABLE", "Image generation runtime is not connected in this build.", correlation, param="model"),
        status_code=503,
        headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
    )
