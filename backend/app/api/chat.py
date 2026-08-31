"""Chat routes with optional user-scoped remote provider selection."""
from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
from core.api_contracts import correlation_id, problem
from core.config import settings
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from models.records import User
from pydantic import BaseModel, Field
from services.chat_service import run_chat, stream_chat
from services.remote_provider_service import RemoteProviderError, RemoteProviderService
from services.runtime_registry import get_runtime
from sqlalchemy.orm import Session

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|developer|user|assistant)$")
    content: str = Field(min_length=1, max_length=200000)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    session_id: int | None = None
    provider_id: int | None = None


def _provider(db: Session, user: User, provider_id: int | None) -> dict | None:
    if provider_id is None:
        return None
    return RemoteProviderService(db, settings.data_dir).resolve(user.id, provider_id)


class _ChatErrorClassification:
    """Shared exception classification for both streaming and non-streaming paths."""
    def __init__(self, code: str, message: str, http_status: int, retryable: bool):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable

    def to_problem(self, corr: str) -> HTTPException:
        return problem(self.http_status, self.code, self.message, correlation=corr)

    def to_stream_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def _classify_chat_exception(exc: Exception) -> _ChatErrorClassification:
    """Classify exception into stable error code. Single source of truth for both paths."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return _ChatErrorClassification("AUTHENTICATION_FAILED", "远程服务拒绝认证。请检查 API Key 后重新验证。", 403, False)
        if status == 429:
            return _ChatErrorClassification("RATE_LIMITED", "远程服务正在限流。请稍后由用户手动重试。", 429, True)
        if status in {404, 405, 501}:
            return _ChatErrorClassification("PROTOCOL_UNSUPPORTED", "远程服务不支持当前协议。请切换兼容协议后重新验证。", 400, False)
        if status >= 500:
            return _ChatErrorClassification("PROVIDER_UNAVAILABLE", "远程服务暂时不可用。请稍后由用户手动重试。", 502, True)
        return _ChatErrorClassification("PROVIDER_HTTP_ERROR", "远程服务返回了意外响应。请重新验证模型服务配置。", 502, False)
    if isinstance(exc, httpx.TimeoutException):
        return _ChatErrorClassification("REQUEST_TIMEOUT", "远程服务请求超时。请检查网络或稍后由用户手动重试。", 504, True)
    if isinstance(exc, httpx.RequestError):
        return _ChatErrorClassification("ENDPOINT_UNREACHABLE", "无法连接远程服务。请检查 Base URL 和网络连接。", 502, True)
    if isinstance(exc, RemoteProviderError):
        return _ChatErrorClassification("PROVIDER_CONFIG_INVALID", "远程模型服务配置无效。请检查提供商设置。", 400, False)
    if isinstance(exc, ValueError):
        return _ChatErrorClassification("REQUEST_INVALID", "请求参数无效。请检查输入后重试。", 400, False)
    if isinstance(exc, PermissionError):
        return _ChatErrorClassification("MODEL_ACCESS_DENIED", "无权访问所选模型。请联系管理员。", 403, False)
    return _ChatErrorClassification("INFERENCE_FAILED", "推理请求失败。请稍后重试。", 502, False)


@router.post("")
async def chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()[:64]
    try:
        result = await run_chat(db, get_runtime(), req.model, [item.model_dump() for item in req.messages], user, req.session_id, _provider(db, user, req.provider_id))
        return result
    except Exception as exc:
        classification = _classify_chat_exception(exc)
        raise classification.to_problem(corr) from exc


@router.post("/stream")
async def chat_stream(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()[:64]
    try:
        provider = _provider(db, user, req.provider_id)
    except RemoteProviderError as exc:
        classification = _classify_chat_exception(exc)
        raise classification.to_problem(corr) from exc

    async def event_generator():
        """Relay model events while emitting heartbeats for client cancellation."""
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        async def produce_events() -> None:
            try:
                async for event in stream_chat(
                    db,
                    get_runtime(),
                    req.model,
                    [item.model_dump() for item in req.messages],
                    user,
                    req.session_id,
                    provider,
                ):
                    await queue.put(("event", event))
            except Exception as exc:
                await queue.put(("error", exc))
            finally:
                await queue.put(("done", None))

        producer = asyncio.create_task(produce_events())
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if kind == "event":
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                elif kind == "error":
                    classification = _classify_chat_exception(payload)
                    yield f"data: {json.dumps({'type': 'error', 'correlation_id': corr, 'data': classification.to_stream_dict()}, ensure_ascii=False)}\n\n"
                elif kind == "done":
                    return
        finally:
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Correlation-ID": corr},
    )
