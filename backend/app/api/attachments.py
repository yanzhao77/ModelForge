"""Managed attachment API for structured chat."""
from __future__ import annotations

from urllib.parse import quote

from core.api_contracts import correlation_id, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from models.records import User
from services.attachment_service import AttachmentError, AttachmentService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/attachments", tags=["attachments"])


def _to_problem(exc: AttachmentError, corr: str):
    status = (
        413 if exc.code == "ATTACHMENT_LIMIT_EXCEEDED"
        else 415 if exc.code == "ATTACHMENT_TYPE_UNSUPPORTED"
        else 409 if exc.code == "ATTACHMENT_IN_USE"
        else 404 if exc.code == "ATTACHMENT_UNAVAILABLE"
        else 400
    )
    return problem(status, exc.code, exc.message, correlation=corr)


@router.post("")
def upload_attachment(
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        rec = AttachmentService().upload_stream(db, user.id, file.filename or "attachment", file.file, file.content_type)
    except AttachmentError as exc:
        raise _to_problem(exc, corr) from exc
    return {**rec.to_dict(), "correlation_id": corr}


@router.post("/cleanup-deleted")
def cleanup_deleted_attachments(
    limit: int = 100,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    result = AttachmentService().cleanup_unreferenced_deleted(db, user_id=user.id, limit=limit)
    return {"ok": True, **result, "correlation_id": corr}


@router.get("/{attachment_id}")
def get_attachment(
    attachment_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        service = AttachmentService()
        rec = service.require(db, user.id, attachment_id)
        return {**rec.to_dict(), "references": service.reference_summary(db, user.id, rec.id)}
    except AttachmentError as exc:
        raise _to_problem(exc, corr) from exc


@router.get("/{attachment_id}/preview")
def preview_attachment(
    attachment_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    service = AttachmentService()
    try:
        rec = service.require(db, user.id, attachment_id)
        return service.preview(db, rec)
    except AttachmentError as exc:
        raise _to_problem(exc, corr) from exc


@router.post("/{attachment_id}/process")
def process_attachment(
    attachment_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return current built-in processing state.

    Heavy OCR/ASR/PDF processors are intentionally not started by this first
    slice; the endpoint exists so clients can use one contract and receive a
    clear processor-unavailable state for unsupported derivations.
    """
    corr = correlation_id()
    service = AttachmentService()
    try:
        rec = service.require(db, user.id, attachment_id)
        return service.preview(db, rec)
    except AttachmentError as exc:
        raise _to_problem(exc, corr) from exc


@router.get("/{attachment_id}/content")
@router.head("/{attachment_id}/content")
def download_attachment(
    attachment_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    service = AttachmentService()
    try:
        rec = service.require(db, user.id, attachment_id)
        path = service.path_for(rec)
    except AttachmentError as exc:
        raise _to_problem(exc, corr) from exc
    filename = quote(rec.display_name, safe="")
    return FileResponse(
        path,
        media_type=rec.mime_type,
        filename=rec.display_name,
        headers={
            "X-Correlation-ID": corr,
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )


@router.get("/{attachment_id}/derivatives/{derivative_id}/content")
@router.head("/{attachment_id}/derivatives/{derivative_id}/content")
def download_attachment_derivative(
    attachment_id: str,
    derivative_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    service = AttachmentService()
    try:
        rec, derivative = service.require_derivative(db, user.id, attachment_id, derivative_id)
        path = service.derivative_path_for(derivative)
    except AttachmentError as exc:
        raise _to_problem(exc, corr) from exc
    metadata = derivative.to_dict().get("metadata") or {}
    media_type = str(metadata.get("thumbnail_mime_type") or rec.mime_type)
    filename = quote(f"{rec.display_name}.{derivative.kind}", safe="")
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"{rec.display_name}.{derivative.kind}",
        headers={
            "X-Correlation-ID": corr,
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    service = AttachmentService()
    try:
        result = service.delete(db, user.id, attachment_id)
    except AttachmentError as exc:
        raise _to_problem(exc, corr) from exc
    return {"ok": True, **result, "correlation_id": corr}
