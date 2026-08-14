"""Session and message API routes."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from core.database import get_db
from core.security import get_current_user
from models.records import User
from services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str = "新对话"
    model_id: Optional[int] = None


class SessionUpdate(BaseModel):
    title: Optional[str] = None


class MessageCreate(BaseModel):
    role: str
    content: str


def _session_or_404(db, session_id, user_id):
    session = SessionService.get_session_by_id(db, session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get("")
def list_sessions(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    sessions = SessionService.get_user_sessions(db, user.id)
    return [
        {
            "id": s.id,
            "title": s.title,
            "model_id": s.model_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "message_count": SessionService.get_session_message_count(db, s.id),
        }
        for s in sessions
    ]


@router.post("")
def create_session(
    req: SessionCreate, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = SessionService.create_session(db, user.id, req.title, req.model_id)
    return {"id": session.id, "title": session.title, "message_count": 0}


@router.get("/{session_id}")
def get_session(
    session_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = _session_or_404(db, session_id, user.id)
    return {
        "id": session.id,
        "title": session.title,
        "model_id": session.model_id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "message_count": SessionService.get_session_message_count(db, session.id),
    }


@router.patch("/{session_id}")
def update_session(
    session_id: int, req: SessionUpdate, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    if req.title is not None:
        SessionService.update_session_title(db, session_id, req.title, user.id)
    return {"ok": True}


@router.delete("/{session_id}")
def delete_session(
    session_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    SessionService.delete_session(db, session_id, user.id)
    return {"ok": True}


@router.get("/{session_id}/messages")
def list_messages(
    session_id: int, limit: Optional[int] = None, offset: Optional[int] = 0,
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    messages = SessionService.get_session_messages(db, session_id, limit, offset)
    return [m.to_dict() for m in messages]


@router.post("/{session_id}/messages")
def add_message(
    session_id: int, req: MessageCreate, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    msg = SessionService.add_message(
        db, session_id, req.role, req.content, token_count=len(req.content)
    )
    return msg.to_dict()


@router.delete("/{session_id}/messages")
def clear_messages(
    session_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    SessionService.clear_session_messages(db, session_id, user.id)
    return {"ok": True}


@router.post("/{session_id}/title")
def auto_title(
    session_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    ok = SessionService.auto_generate_title(db, session_id)
    if not ok:
        raise HTTPException(status_code=400, detail="无法生成标题")
    session = SessionService.get_session_by_id(db, session_id)
    return {"ok": True, "title": session.title}