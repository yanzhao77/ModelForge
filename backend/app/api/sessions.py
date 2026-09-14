"""Session and message API routes."""

from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from models.records import User
from pydantic import BaseModel
from services.artifact_service import ArtifactService
from services.attachment_service import AttachmentService
from services.session_service import SessionService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str = "新对话"
    model_id: int | None = None


class SessionUpdate(BaseModel):
    title: str | None = None


class MessageCreate(BaseModel):
    role: str
    content: str


class MessagePinUpdate(BaseModel):
    pinned: bool


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
    session_id: int, limit: int | None = None, offset: int | None = 0,
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    messages = SessionService.get_session_messages(db, session_id, limit, offset)
    return [m.to_dict() for m in messages]


@router.get("/{session_id}/messages/search")
def search_messages(
    session_id: int,
    q: str = "",
    limit: int = 50,
    pinned_only: bool = False,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    messages = SessionService.search_session_messages(db, session_id, q, limit=limit, pinned_only=pinned_only)
    return [m.to_dict() for m in messages]


@router.patch("/{session_id}/messages/{message_id}/pin")
def update_message_pin(
    session_id: int,
    message_id: int,
    req: MessagePinUpdate,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    message = SessionService.set_message_pinned(db, session_id, message_id, req.pinned)
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    return message.to_dict()


@router.get("/{session_id}/attachments")
def list_session_attachments(
    session_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    return [item.to_dict() for item in AttachmentService().list_for_session(db, user.id, session_id)]


@router.get("/{session_id}/artifacts")
def list_session_artifacts(
    session_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    return [item.to_dict() for item in ArtifactService().list_for_session(db, user.id, session_id)]


@router.get("/{session_id}/export")
def export_session(
    session_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    return SessionService.export_session(db, session_id, user.id)


@router.get("/{session_id}/storage")
def session_storage_usage(
    session_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _session_or_404(db, session_id, user.id)
    return SessionService.storage_usage(db, session_id, user.id)


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
