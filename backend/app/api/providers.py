"""Authenticated remote provider configuration endpoints."""
from __future__ import annotations

from typing import Literal

from core.api_contracts import correlation_id, operation_result, problem
from core.config import settings
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends
from models.records import User
from pydantic import BaseModel, Field
from services.remote_provider_service import RemoteProviderError, RemoteProviderService
from sqlalchemy.orm import Session

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=8, max_length=512)
    protocol: Literal["responses", "chat_completions"] = "responses"
    default_model: str = Field(min_length=1, max_length=255)
    api_key: str | None = Field(default=None, min_length=1, max_length=2048)
    request_id: str | None = Field(default=None, max_length=64)


class ProviderVerifyRequest(BaseModel):
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


def _service(db: Session) -> RemoteProviderService:
    return RemoteProviderService(db, settings.data_dir)


@router.get("")
def list_providers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"providers": _service(db).list(user.id)}


@router.post("")
def save_provider(req: ProviderUpsert, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    corr = req.request_id or correlation_id()
    try:
        payload = req.model_dump(exclude={"request_id"})
        return operation_result(_service(db).save(user.id, **payload), corr)
    except RemoteProviderError as exc:
        code = getattr(exc, "code", None) or "REMOTE_PROVIDER_INVALID"
        raise problem(400, code, "Remote provider configuration is invalid.", correlation=corr) from exc


@router.delete("/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    corr = correlation_id()
    try:
        _service(db).delete(user.id, provider_id)
        return operation_result({"ok": True, "id": provider_id}, corr)
    except RemoteProviderError as exc:
        raise problem(404, "REMOTE_PROVIDER_NOT_FOUND", "Remote provider was not found.", correlation=corr) from exc


@router.post("/{provider_id}/verify")
def verify_provider(
    provider_id: int,
    req: ProviderVerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(
            409,
            "REMOTE_PROVIDER_VERIFY_CONFIRMATION_REQUIRED",
            "Explicit confirmation is required before contacting a remote provider.",
            correlation=corr,
        )
    try:
        return operation_result(_service(db).verify(user.id, provider_id), corr)
    except RemoteProviderError as exc:
        code = getattr(exc, "code", None) or "REMOTE_PROVIDER_VERIFICATION_FAILED"
        raise problem(
            400,
            code,
            "Remote provider verification did not complete.",
            correlation=corr,
        ) from exc
