"""Session and message management (DB-backed, ported from legacy app)."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from models.records import Session, Message


class SessionService:
    """CRUD for sessions and messages, with user ownership checks."""

    @staticmethod
    def create_session(
        db: DBSession, user_id: int, title: str = "新对话", model_id: Optional[int] = None
    ) -> Session:
        session = Session(
            user_id=user_id,
            title=title,
            model_id=model_id,
            is_active=True,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def get_user_sessions(
        db: DBSession, user_id: int, include_inactive: bool = False
    ) -> List[Session]:
        query = db.query(Session).filter(Session.user_id == user_id)
        if not include_inactive:
            query = query.filter(Session.is_active.is_(True))
        return query.order_by(Session.updated_at.desc()).all()

    @staticmethod
    def get_session_by_id(
        db: DBSession, session_id: int, user_id: Optional[int] = None
    ) -> Optional[Session]:
        query = db.query(Session).filter(Session.id == session_id)
        if user_id is not None:
            query = query.filter(Session.user_id == user_id)
        return query.first()

    @staticmethod
    def update_session_title(
        db: DBSession, session_id: int, title: str, user_id: Optional[int] = None
    ) -> bool:
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        session.title = title
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True

    @staticmethod
    def delete_session(
        db: DBSession, session_id: int, user_id: Optional[int] = None
    ) -> bool:
        """Soft delete a session."""
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        session.is_active = False
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True

    @staticmethod
    def hard_delete_session(
        db: DBSession, session_id: int, user_id: Optional[int] = None
    ) -> bool:
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        db.delete(session)
        db.commit()
        return True

    @staticmethod
    def add_message(
        db: DBSession, session_id: int, role: str, content: str, token_count: int = 0
    ) -> Message:
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
        )
        db.add(message)
        session = db.query(Session).filter(Session.id == session_id).first()
        if session:
            session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(message)
        return message

    @staticmethod
    def get_session_messages(
        db: DBSession, session_id: int, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Message]:
        query = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.timestamp.asc(), Message.id.asc())
        )
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        return query.all()

    @staticmethod
    def get_session_history(
        db: DBSession, session_id: int, limit: Optional[int] = None
    ) -> List[dict]:
        messages = SessionService.get_session_messages(db, session_id, limit)
        return [m.to_dict() for m in messages]

    @staticmethod
    def clear_session_messages(
        db: DBSession, session_id: int, user_id: Optional[int] = None
    ) -> bool:
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        db.query(Message).filter(Message.session_id == session_id).delete()
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True

    @staticmethod
    def get_session_message_count(db: DBSession, session_id: int) -> int:
        return db.query(Message).filter(Message.session_id == session_id).count()

    @staticmethod
    def auto_generate_title(db: DBSession, session_id: int) -> bool:
        """Auto title from the first user message (max 30 chars)."""
        first = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.timestamp.asc(), Message.id.asc())
            .first()
        )
        if not first or first.role != "user":
            return False
        content = first.content.strip()
        if not content:
            return False
        title = content[:30] + ("..." if len(content) > 30 else "")
        return SessionService.update_session_title(db, session_id, title)