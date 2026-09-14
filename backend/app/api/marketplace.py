"""Agent Marketplace API (V3.2)."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import record_operation
from services.marketplace_service import MarketplaceService
from services.package_service import SUPPORTED_KINDS, PackageError
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


class MarketplaceInstallRequest(BaseModel):
    package_id: str | None = Field(default=None, max_length=160)
    version: str | None = Field(default=None, max_length=40)
    document: dict | None = None
    conflict: str = Field(default="rename", max_length=16)


def _service(db: DBSession) -> MarketplaceService:
    return MarketplaceService(db)


def _marketplace_problem(exc: PackageError, corr: str):
    return problem(exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None)


@router.get("")
def search_marketplace(
    query: str | None = None,
    kind: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"items": _service(db).search(user.id, query=query, kind=kind), "kinds": list(SUPPORTED_KINDS)}


@router.get("/{package_id}")
def marketplace_detail(
    package_id: str,
    version: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return _service(db).detail(user.id, package_id, version)
    except PackageError as exc:
        raise _marketplace_problem(exc, correlation_id()) from exc


@router.post("/install")
def install_marketplace_package(
    req: MarketplaceInstallRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        result = _service(db).install(
            user.id,
            req.document,
            package_id=req.package_id,
            version=req.version,
            conflict=req.conflict,
        )
    except PackageError as exc:
        raise _marketplace_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="marketplace.install",
        object_type="package",
        object_id=result["package_id"],
        correlation_id=corr,
        metadata={"kind": result["kind"], "missing": len(result.get("missing_dependencies") or [])},
    )
    db.commit()
    return operation_result(result, corr)


@router.delete("/{package_id}")
def uninstall_marketplace_package(
    package_id: str,
    version: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        result = _service(db).uninstall(user.id, package_id, version)
    except PackageError as exc:
        raise _marketplace_problem(exc, corr) from exc
    record_operation(
        db,
        user_id=user.id,
        action="marketplace.uninstall",
        object_type="package",
        object_id=package_id,
        correlation_id=corr,
        metadata={"removed": result["removed"]},
    )
    db.commit()
    return operation_result(result, corr)
