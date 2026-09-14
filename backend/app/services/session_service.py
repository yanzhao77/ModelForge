import json
from datetime import datetime, timezone

from models.records import (
    ArtifactRecord,
    ArtifactVersionRecord,
    AttachmentRecord,
    Message,
    MessageAttachment,
    Session,
)
from sqlalchemy.orm import Session as DBSession


class SessionService:
    """CRUD for sessions and messages, with user ownership checks."""

    @staticmethod
    def create_session(
        db: DBSession, user_id: int, title: str = "新对话", model_id: int | None = None
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
    ) -> list[Session]:
        query = db.query(Session).filter(Session.user_id == user_id)
        if not include_inactive:
            query = query.filter(Session.is_active.is_(True))
        return query.order_by(Session.updated_at.desc()).all()

    @staticmethod
    def get_session_by_id(
        db: DBSession, session_id: int, user_id: int | None = None
    ) -> Session | None:
        query = db.query(Session).filter(Session.id == session_id)
        if user_id is not None:
            query = query.filter(Session.user_id == user_id)
        return query.first()

    @staticmethod
    def update_session_title(
        db: DBSession, session_id: int, title: str, user_id: int | None = None
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
        db: DBSession, session_id: int, user_id: int | None = None
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
        db: DBSession, session_id: int, user_id: int | None = None
    ) -> bool:
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        db.delete(session)
        db.commit()
        return True

    @staticmethod
    def add_message(
        db: DBSession,
        session_id: int,
        role: str,
        content: str,
        token_count: int = 0,
        *,
        parts: list[dict] | None = None,
        schema_version: int = 1,
        status: str = "completed",
        turn_id: str | None = None,
        parent_message_id: int | None = None,
    ) -> Message:
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
            schema_version=schema_version,
            parts_json=json.dumps(parts, ensure_ascii=False) if parts is not None else None,
            status=status,
            turn_id=turn_id,
            parent_message_id=parent_message_id,
        )
        db.add(message)
        session = db.query(Session).filter(Session.id == session_id).first()
        if session:
            session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(message)
        return message

    @staticmethod
    def link_message_attachment(
        db: DBSession,
        message_id: int,
        attachment_id: str,
        scope: str = "message",
    ) -> MessageAttachment:
        edge = MessageAttachment(message_id=message_id, attachment_id=attachment_id, scope=scope)
        db.add(edge)
        db.flush()
        return edge

    @staticmethod
    def get_session_messages(
        db: DBSession, session_id: int, limit: int | None = None, offset: int | None = None
    ) -> list[Message]:
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
    def search_session_messages(
        db: DBSession,
        session_id: int,
        query_text: str,
        *,
        limit: int = 50,
        pinned_only: bool = False,
    ) -> list[Message]:
        query = db.query(Message).filter(Message.session_id == session_id)
        if pinned_only:
            query = query.filter(Message.is_pinned.is_(True))
        text = query_text.strip()
        if text:
            query = query.filter(Message.content.ilike(f"%{text}%"))
        return query.order_by(Message.timestamp.asc(), Message.id.asc()).limit(max(1, min(limit, 200))).all()

    @staticmethod
    def set_message_pinned(
        db: DBSession,
        session_id: int,
        message_id: int,
        pinned: bool,
    ) -> Message | None:
        message = db.query(Message).filter(Message.id == message_id, Message.session_id == session_id).first()
        if message is None:
            return None
        message.is_pinned = pinned
        message.pinned_at = datetime.now(timezone.utc) if pinned else None
        session = db.query(Session).filter(Session.id == session_id).first()
        if session:
            session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(message)
        return message

    @staticmethod
    def export_session(db: DBSession, session_id: int, user_id: int) -> dict:
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if session is None:
            return {}
        messages = SessionService.get_session_messages(db, session_id)
        attachments = (
            db.query(AttachmentRecord)
            .join(MessageAttachment, MessageAttachment.attachment_id == AttachmentRecord.id)
            .join(Message, Message.id == MessageAttachment.message_id)
            .filter(Message.session_id == session_id, AttachmentRecord.user_id == user_id)
            .order_by(AttachmentRecord.created_at.asc())
            .all()
        )
        artifacts = (
            db.query(ArtifactRecord)
            .filter(ArtifactRecord.session_id == session_id, ArtifactRecord.user_id == user_id)
            .order_by(ArtifactRecord.created_at.asc())
            .all()
        )
        artifact_ids = [artifact.id for artifact in artifacts]
        versions = []
        if artifact_ids:
            versions = (
                db.query(ArtifactVersionRecord)
                .filter(ArtifactVersionRecord.artifact_id.in_(artifact_ids))
                .order_by(ArtifactVersionRecord.artifact_id.asc(), ArtifactVersionRecord.version.asc())
                .all()
            )
        return {
            "schema_version": 1,
            "privacy": {
                "includes_raw_attachment_bytes": False,
                "includes_internal_storage_paths": False,
                "includes_credentials": False,
            },
            "session": {
                "id": session.id,
                "title": session.title,
                "model_id": session.model_id,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            },
            "messages": [message.to_dict() for message in messages],
            "attachments": [attachment.to_dict() for attachment in attachments],
            "artifacts": [artifact.to_dict() for artifact in artifacts],
            "artifact_versions": [version.to_dict() for version in versions],
        }

    @staticmethod
    def storage_usage(db: DBSession, session_id: int, user_id: int) -> dict:
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if session is None:
            return {}
        input_attachments = (
            db.query(AttachmentRecord)
            .join(MessageAttachment, MessageAttachment.attachment_id == AttachmentRecord.id)
            .join(Message, Message.id == MessageAttachment.message_id)
            .filter(Message.session_id == session_id, AttachmentRecord.user_id == user_id)
            .all()
        )
        artifacts = db.query(ArtifactRecord).filter(ArtifactRecord.session_id == session_id, ArtifactRecord.user_id == user_id).all()
        artifact_ids = [artifact.id for artifact in artifacts]
        versions = []
        if artifact_ids:
            versions = db.query(ArtifactVersionRecord).filter(ArtifactVersionRecord.artifact_id.in_(artifact_ids)).all()
        input_ids = {attachment.id for attachment in input_attachments}
        artifact_attachment_ids = {version.attachment_id for version in versions}
        all_attachment_ids = input_ids | artifact_attachment_ids
        all_attachments = db.query(AttachmentRecord).filter(AttachmentRecord.id.in_(all_attachment_ids)).all() if all_attachment_ids else []
        return {
            "session_id": session_id,
            "input_attachment_count": len(input_ids),
            "artifact_count": len(artifacts),
            "artifact_version_count": len(versions),
            "managed_attachment_count": len(all_attachment_ids),
            "input_bytes": sum(attachment.size_bytes for attachment in input_attachments),
            "artifact_bytes": sum(version.size_bytes for version in versions),
            "managed_bytes": sum(attachment.size_bytes for attachment in all_attachments),
            "cleanup_policy": "Only deleted attachments with no message references are physically removed by the cleanup endpoint.",
        }

    @staticmethod
    def get_session_history(
        db: DBSession, session_id: int, limit: int | None = None
    ) -> list[dict]:
        messages = SessionService.get_session_messages(db, session_id, limit)
        return [m.to_dict() for m in messages]

    @staticmethod
    def get_recent_session_messages(
        db: DBSession, session_id: int, limit: int = 50
    ) -> list[Message]:
        """Return the newest ``limit`` messages, oldest first.

        A context window must carry the *latest* turns; ``get_session_messages``
        pages from the beginning of the conversation, which silently dropped
        everything said after the window filled up.
        """
        rows = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(max(1, limit))
            .all()
        )
        return list(reversed(rows))

    @staticmethod
    def clear_session_messages(
        db: DBSession, session_id: int, user_id: int | None = None
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
