"""Chat artifact API."""
from __future__ import annotations

from urllib.parse import quote

from core.api_contracts import correlation_id, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from models.records import ArtifactRecord, ArtifactVersionRecord, User
from pydantic import BaseModel, Field
from services.artifact_service import ArtifactError, ArtifactService
from services.attachment_service import AttachmentError, AttachmentService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactVersionCreate(BaseModel):
    expected_version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=2_000_000)
    mime_type: str = Field(default="text/plain", pattern="^(text/plain|text/markdown|application/json|text/csv|text/tab-separated-values)$")


def _artifact_or_404(db: DBSession, user_id: int, artifact_id: str) -> ArtifactRecord:
    artifact = db.query(ArtifactRecord).filter(ArtifactRecord.id == artifact_id, ArtifactRecord.user_id == user_id).first()
    if artifact is None:
        raise problem(404, "ARTIFACT_NOT_FOUND", "Artifact was not found.", correlation=correlation_id())
    return artifact


@router.get("/{artifact_id}/versions")
def list_versions(
    artifact_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _artifact_or_404(db, user.id, artifact_id)
    versions = (
        db.query(ArtifactVersionRecord)
        .filter(ArtifactVersionRecord.artifact_id == artifact_id)
        .order_by(ArtifactVersionRecord.version.asc())
        .all()
    )
    return [version.to_dict() for version in versions]


@router.post("/{artifact_id}/versions", status_code=201)
def create_version(
    artifact_id: str,
    req: ArtifactVersionCreate,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        artifact, version = ArtifactService().create_text_version(
            db,
            user_id=user.id,
            artifact_id=artifact_id,
            expected_version=req.expected_version,
            content=req.content,
            mime_type=req.mime_type,
        )
        return {"artifact": artifact.to_dict(), "version": version.to_dict(), "correlation_id": corr}
    except ArtifactError as exc:
        status_code = 409 if exc.code == "ARTIFACT_VERSION_CONFLICT" else 404 if exc.code == "ARTIFACT_NOT_FOUND" else 400
        raise problem(status_code, exc.code, exc.message, correlation=corr) from exc
    except AttachmentError as exc:
        raise problem(400, exc.code, exc.message, correlation=corr) from exc


@router.get("/{artifact_id}/versions/{version}/content")
@router.head("/{artifact_id}/versions/{version}/content")
def download_version(
    artifact_id: str,
    version: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    artifact = _artifact_or_404(db, user.id, artifact_id)
    row = (
        db.query(ArtifactVersionRecord)
        .filter(ArtifactVersionRecord.artifact_id == artifact_id, ArtifactVersionRecord.version == version)
        .first()
    )
    if row is None:
        raise problem(404, "ARTIFACT_VERSION_NOT_FOUND", "Artifact version was not found.", correlation=corr)
    service = AttachmentService()
    try:
        attachment = service.require(db, user.id, row.attachment_id)
        path = service.path_for(attachment)
    except AttachmentError as exc:
        raise problem(404, exc.code, exc.message, correlation=corr) from exc
    filename = quote(artifact.name, safe="")
    return FileResponse(
        path,
        media_type=attachment.mime_type,
        filename=artifact.name,
        headers={
            "X-Correlation-ID": corr,
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )
