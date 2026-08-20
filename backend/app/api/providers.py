"""Authenticated remote provider configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.security import get_current_user
from models.records import User
from services.remote_provider_service import RemoteProviderError, RemoteProviderService

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str
    protocol: str = "responses"
    default_model: str = Field(min_length=1, max_length=255)
    api_key: str | None = Field(default=None, min_length=1, max_length=2048)


def _service(db: Session) -> RemoteProviderService:
    return RemoteProviderService(db, settings.data_dir)


@router.get("")
def list_providers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"providers": _service(db).list(user.id)}


@router.post("")
def save_provider(req: ProviderUpsert, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return _service(db).save(user.id, **req.model_dump())
    except RemoteProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        _service(db).delete(user.id, provider_id)
        return {"ok": True}
    except RemoteProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{provider_id}/verify")
def verify_provider(provider_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return _service(db).verify(user.id, provider_id)
    except RemoteProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
