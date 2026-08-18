"""Chat API routes: JSON chat + SSE streaming."""
import json

from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from models.records import User
from pydantic import BaseModel
from services.chat_service import run_chat, stream_chat
from services.runtime_registry import get_runtime
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    session_id: int | None = None


@router.post("")
async def chat(
    req: ChatRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        result = await run_chat(
            db, get_runtime(), req.model, messages, user, req.session_id
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"聊天失败: {e}")


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_generator():
        try:
            async for event in stream_chat(
                db, get_runtime(), req.model, messages, user, req.session_id
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except PermissionError as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"
        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': f'聊天失败: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )