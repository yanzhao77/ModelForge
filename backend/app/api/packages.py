"""Package export/import API (V1.7)."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import record_operation
from services.package_service import SUPPORTED_KINDS, PackageError, PackageService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/packages", tags=["packages"])


class PackageExportRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=24)
    ref: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=40)
    license: str | None = Field(default=None, max_length=120)


class PackageImportRequest(BaseModel):
    document: dict
    conflict: str = Field(default="rename", max_length=16)


def _service(db: DBSession) -> PackageService:
    return PackageService(db)


def _problem(exc: PackageError, corr: str):
    return problem(
        exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None
    )


@router.get("")
def list_packages(
    kind: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"packages": _service(db).list(user.id, kind=kind), "kinds": list(SUPPORTED_KINDS)}


@router.post("/export")
def export_package(
    req: PackageExportRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        document = _service(db).export(
            user.id, kind=req.kind, ref=req.ref, version=req.version, license_name=req.license
        )
    except PackageError as exc:
        raise _problem(exc, corr) from exc
    record_operation(
        db, user_id=user.id, action="package.export", object_type="package",
        object_id=document["manifest"]["package_id"], correlation_id=corr,
        metadata={"kind": document["manifest"]["kind"], "version": document["manifest"]["version"]},
    )
    db.commit()
    return operation_result(document, corr)


@router.post("/import")
def import_package(
    req: PackageImportRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        result = _service(db).import_document(user.id, req.document, conflict=req.conflict)
    except PackageError as exc:
        raise _problem(exc, corr) from exc
    record_operation(
        db, user_id=user.id, action="package.import", object_type="package",
        object_id=result["package_id"], correlation_id=corr,
        metadata={"kind": result["kind"], "missing": len(result["missing_dependencies"])},
    )
    db.commit()
    return operation_result(result, corr)


@router.get("/{package_id}")
def get_package(
    package_id: str,
    version: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        service = _service(db)
        document = service.get(user.id, package_id, version)
    except PackageError as exc:
        raise _problem(exc, correlation_id()) from exc
    document["versions"] = service.versions(user.id, package_id)
    return document


@router.delete("/{package_id}")
def delete_package(
    package_id: str,
    version: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    removed = _service(db).delete(user.id, package_id, version)
    if not removed:
        raise problem(404, "PACKAGE_NOT_FOUND", "Package not found.", correlation=correlation_id())
    return {"ok": True, "removed": removed}
