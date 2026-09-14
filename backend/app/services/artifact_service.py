"""Versioned artifact storage backed by managed attachments."""
from __future__ import annotations

import datetime as dt
import io
import json
import uuid

from models.records import ArtifactRecord, ArtifactVersionRecord
from services.attachment_service import AttachmentService
from sqlalchemy.orm import Session as DBSession


class ArtifactError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


class ArtifactService:
    def create_text_artifact(
        self,
        db: DBSession,
        *,
        user_id: int,
        session_id: int | None,
        message_id: int | None,
        name: str,
        content: str,
        mime_type: str = "text/plain",
        producer_ref: str | None = None,
    ) -> tuple[ArtifactRecord, ArtifactVersionRecord]:
        filename = _safe_text_filename(name, mime_type)
        attachment = AttachmentService().upload_stream(
            db,
            user_id,
            filename,
            io.BytesIO(content.encode("utf-8")),
            mime_type,
        )
        now = dt.datetime.utcnow()
        artifact = ArtifactRecord(
            id=f"art_{uuid.uuid4().hex}",
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            name=filename,
            artifact_type="file",
            producer_ref=producer_ref,
            current_version=1,
            created_at=now,
            updated_at=now,
        )
        version = ArtifactVersionRecord(
            id=f"av_{uuid.uuid4().hex}",
            artifact_id=artifact.id,
            version=1,
            attachment_id=attachment.id,
            parent_version=None,
            sha256=attachment.sha256,
            size_bytes=attachment.size_bytes,
            metadata_json=json.dumps({"mime_type": mime_type}, ensure_ascii=False),
            created_at=now,
        )
        db.add(artifact)
        db.add(version)
        db.commit()
        db.refresh(artifact)
        db.refresh(version)
        return artifact, version

    def list_for_session(self, db: DBSession, user_id: int, session_id: int) -> list[ArtifactRecord]:
        return (
            db.query(ArtifactRecord)
            .filter(ArtifactRecord.user_id == user_id, ArtifactRecord.session_id == session_id)
            .order_by(ArtifactRecord.created_at.desc())
            .all()
        )

    def versions(self, db: DBSession, user_id: int, artifact_id: str) -> list[ArtifactVersionRecord]:
        artifact = db.query(ArtifactRecord).filter(ArtifactRecord.id == artifact_id, ArtifactRecord.user_id == user_id).first()
        if artifact is None:
            return []
        return (
            db.query(ArtifactVersionRecord)
            .filter(ArtifactVersionRecord.artifact_id == artifact_id)
            .order_by(ArtifactVersionRecord.version.asc())
            .all()
        )

    def create_text_version(
        self,
        db: DBSession,
        *,
        user_id: int,
        artifact_id: str,
        expected_version: int,
        content: str,
        mime_type: str = "text/plain",
    ) -> tuple[ArtifactRecord, ArtifactVersionRecord]:
        artifact = db.query(ArtifactRecord).filter(ArtifactRecord.id == artifact_id, ArtifactRecord.user_id == user_id).first()
        if artifact is None:
            raise ArtifactError("ARTIFACT_NOT_FOUND", "Artifact was not found.")
        if artifact.current_version != expected_version:
            raise ArtifactError("ARTIFACT_VERSION_CONFLICT", "Artifact version changed before the update was applied.")
        attachment = AttachmentService().upload_stream(
            db,
            user_id,
            artifact.name,
            io.BytesIO(content.encode("utf-8")),
            mime_type,
        )
        now = dt.datetime.utcnow()
        next_version = expected_version + 1
        version = ArtifactVersionRecord(
            id=f"av_{uuid.uuid4().hex}",
            artifact_id=artifact.id,
            version=next_version,
            attachment_id=attachment.id,
            parent_version=expected_version,
            sha256=attachment.sha256,
            size_bytes=attachment.size_bytes,
            metadata_json=json.dumps({"mime_type": mime_type}, ensure_ascii=False),
            created_at=now,
        )
        artifact.current_version = next_version
        artifact.updated_at = now
        db.add(version)
        db.commit()
        db.refresh(artifact)
        db.refresh(version)
        return artifact, version


def _safe_text_filename(name: str, mime_type: str) -> str:
    suffix = {
        "text/markdown": ".md",
        "application/json": ".json",
        "text/csv": ".csv",
        "text/tab-separated-values": ".tsv",
    }.get(mime_type, ".txt")
    cleaned = (name or "response").strip()[:160] or "response"
    if not cleaned.lower().endswith(suffix):
        cleaned = f"{cleaned}{suffix}"
    return cleaned
