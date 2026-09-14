"""JWT-authenticated control plane for the local OpenAI-compatible API."""
from __future__ import annotations

import datetime as dt

from core.api_contracts import correlation_id
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from models.records import User
from pydantic import BaseModel, Field
from services.local_api_service import (
    DEFAULT_LOCAL_API_SCOPES,
    LocalApiError,
    LocalApiService,
    openai_error_payload,
)
from services.model_runtime_manager import ModelRuntimeError, get_model_runtime_manager
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/local-api", tags=["local-api"])


class LocalApiSettingsRequest(BaseModel):
    enabled: bool | None = None
    host: str | None = Field(default=None, max_length=128)
    port: int | None = Field(default=None, ge=1, le=65535)
    cors_origins: list[str] | None = None
    max_concurrent_requests: int | None = Field(default=None, ge=1, le=64)
    max_concurrent_requests_per_model: int | None = Field(default=None, ge=1, le=32)
    queue_size: int | None = Field(default=None, ge=0, le=1024)
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=3600)
    idle_unload_seconds: int | None = Field(default=None, ge=0, le=86400)
    max_upload_bytes: int | None = Field(default=None, ge=1024, le=1024 * 1024 * 1024)
    auto_load_models: bool | None = None
    allow_lan: bool | None = None
    logging_enabled: bool | None = None
    log_retention_days: int | None = Field(default=None, ge=1, le=365)
    temp_dir: str | None = Field(default=None, max_length=1024)


class LocalApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] | None = None
    expires_at: dt.datetime | None = None


class LocalApiAliasRequest(BaseModel):
    alias: str | None = Field(default=None, max_length=255)


class LocalApiTestRequest(BaseModel):
    message: str = Field(default="ping", min_length=1, max_length=2000)


def _headers(correlation: str) -> dict[str, str]:
    return {"X-Request-ID": correlation, "X-Correlation-ID": correlation}


def _error(exc: LocalApiError, correlation: str) -> JSONResponse:
    return JSONResponse(
        openai_error_payload(exc.code, exc.message, correlation, param=exc.param),
        status_code=exc.status_code,
        headers=_headers(correlation),
    )


@router.get("/status")
def local_api_status(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return LocalApiService(db).status(user.id)


@router.put("/settings")
def update_local_api_settings(req: LocalApiSettingsRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return LocalApiService(db).update_settings(user.id, req.model_dump(exclude_unset=True))
    except LocalApiError as exc:
        return _error(exc, correlation_id()[:64])


@router.post("/start")
def start_local_api(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return LocalApiService(db).update_settings(user.id, {"enabled": True})


@router.post("/stop")
def stop_local_api(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return LocalApiService(db).update_settings(user.id, {"enabled": False})


@router.post("/restart")
def restart_local_api(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    # In the embedded FastAPI process, restart means re-enabling the local API
    # contract with the latest persisted settings. The desktop process owns the
    # actual HTTP listener lifecycle.
    return {"status": "restarted", "settings": LocalApiService(db).update_settings(user.id, {"enabled": True})}


@router.get("/keys")
def list_local_api_keys(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"keys": LocalApiService(db).list_keys(user.id), "available_scopes": sorted(DEFAULT_LOCAL_API_SCOPES)}


@router.post("/keys")
def create_local_api_key(req: LocalApiKeyRequest, request_id: str | None = Header(default=None, alias="X-Request-ID"), db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = (request_id or correlation_id())[:64]
    try:
        key, secret = LocalApiService(db).issue_key(user.id, req.name, req.scopes, req.expires_at)
    except LocalApiError as exc:
        return _error(exc, corr)
    return JSONResponse({"key": key.to_dict(), "secret": secret}, headers=_headers(corr))


@router.post("/keys/{key_id}/enable")
def enable_local_api_key(key_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return {"key": LocalApiService(db).set_key_enabled(user.id, key_id, True)}
    except LocalApiError as exc:
        return _error(exc, correlation_id()[:64])


@router.post("/keys/{key_id}/disable")
def disable_local_api_key(key_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return {"key": LocalApiService(db).set_key_enabled(user.id, key_id, False)}
    except LocalApiError as exc:
        return _error(exc, correlation_id()[:64])


@router.post("/keys/{key_id}/revoke")
def revoke_local_api_key(key_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return {"key": LocalApiService(db).revoke_key(user.id, key_id)}
    except LocalApiError as exc:
        return _error(exc, correlation_id()[:64])


@router.delete("/keys/{key_id}")
def delete_local_api_key(key_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        key = LocalApiService(db).revoke_key(user.id, key_id)
        return {"deleted": True, "key": key}
    except LocalApiError as exc:
        return _error(exc, correlation_id()[:64])


@router.get("/models")
def list_local_api_models(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"models": LocalApiService(db).list_model_descriptors(user.id)}


@router.put("/models/{model_id}/alias")
def update_model_alias(model_id: int, req: LocalApiAliasRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return {"model": LocalApiService(db).set_alias(user.id, model_id, req.alias)}
    except LocalApiError as exc:
        return _error(exc, correlation_id()[:64])


@router.post("/models/{model_id}/load")
async def load_api_model(model_id: int, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        instance = await get_model_runtime_manager().load(model_id, user.id, db=db)
    except ModelRuntimeError as exc:
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, correlation_id()[:64]),
            status_code=exc.http_status,
        )
    return {"instance": instance.to_dict(), "status": "loaded"}


@router.post("/models/{model_id}/unload")
async def unload_api_model(model_id: int, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return await get_model_runtime_manager().unload(model_id, user.id, db=db)
    except ModelRuntimeError as exc:
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, correlation_id()[:64]),
            status_code=exc.http_status,
        )


@router.post("/models/{model_id}/test")
async def test_api_model(model_id: int, req: LocalApiTestRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        result = await get_model_runtime_manager().chat(model_id, [{"role": "user", "content": req.message}], user_id=user.id)
    except ModelRuntimeError as exc:
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, correlation_id()[:64]),
            status_code=exc.http_status,
        )
    return {"model_id": model_id, "content": result.get("content", "")}


@router.get("/logs")
def list_local_api_logs(limit: int = 100, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"logs": LocalApiService(db).list_logs(user.id, limit=limit)}


@router.delete("/logs")
def clear_local_api_logs(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return LocalApiService(db).clear_logs(user.id)
