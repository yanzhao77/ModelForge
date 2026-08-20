"""Chat routes with optional user-scoped remote provider selection."""
from __future__ import annotations

import json

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


@router.post("")
async def chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        result = await run_chat(db, get_runtime(), req.model, [item.model_dump() for item in req.messages], user, req.session_id, _provider(db, user, req.provider_id))
        return result
    except (RemoteProviderError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chat request failed: {exc}") from exc


@router.post("/stream")
async def chat_stream(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        provider = _provider(db, user, req.provider_id)
    except RemoteProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_generator():
        try:
            async for event in stream_chat(db, get_runtime(), req.model, [item.model_dump() for item in req.messages], user, req.session_id, provider):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'data': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
