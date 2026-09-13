"""Chat routes with optional user-scoped remote provider selection."""
from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
from core.api_contracts import correlation_id, problem
from core.config import settings
from core.database import get_db
from core.network_security import ProviderNetworkError
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from models.records import User
from pydantic import BaseModel, Field
from services.chat_service import run_chat, stream_chat
from services.inference_errors import (
    InferenceErrorClassification,
    classify_inference_exception,
)
from services.remote_provider_service import RemoteProviderError, RemoteProviderService
from services.resource_lease import ResourceBusy, inference_lease, transient_hold
from services.runtime_registry import get_runtime
from sqlalchemy.orm import Session

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|developer|user|assistant)$")
    content: str = Field(min_length=1, max_length=200000)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    # Registry-backed local models are addressed by their stable model_id; the
    # ``model`` field stays required so metrics, sessions and legacy clients
    # keep working (the chat UI sends both).
    model_id: int | None = None
    #: V1.2: force one runtime adapter for a registry model (e.g. "transformers").
    runtime: str | None = Field(default=None, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    session_id: int | None = None
    provider_id: int | None = None


def _provider(db: Session, user: User, provider_id: int | None) -> dict | None:
    if provider_id is None:
        return None
    return RemoteProviderService(db, settings.data_dir).resolve(user.id, provider_id)


# Single classifier shared with the RAG answer route; the aliases keep the
# existing names (and the leakage test importing them) working.
_ChatErrorClassification = InferenceErrorClassification
_classify_chat_exception = classify_inference_exception


@router.post("")
async def chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()[:64]
    try:
        # Inference is exclusive: only one account may run it at a time.
        with transient_hold(inference_lease, user_id=user.id, username=user.username):
            result = await run_chat(
                db,
                get_runtime(),
                req.model,
                [item.model_dump() for item in req.messages],
                user,
                req.session_id,
                _provider(db, user, req.provider_id),
                model_id=req.model_id,
                runtime_id=req.runtime,
            )
            return result
    except ResourceBusy as exc:
        raise exc.to_problem(corr) from exc
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
    try:
        handle = inference_lease.acquire(user_id=user.id, username=user.username)
    except ResourceBusy as exc:
        raise exc.to_problem(corr) from exc

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
                    model_id=req.model_id,
                    runtime_id=req.runtime,
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
            if handle.created:
                handle.release()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Correlation-ID": corr},
    )
