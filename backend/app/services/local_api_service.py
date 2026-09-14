"""Local OpenAI-compatible API control plane and auth primitives."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core.config import settings
from fastapi import Header
from models.records import (
    LocalApiKey,
    LocalApiRequestLog,
    LocalApiSetting,
    ModelApiAlias,
    ModelRecord,
)
from services.model_capabilities import ModelCapability
from services.model_registry import ModelRegistry
from services.model_resolver import ModelResolver
from services.model_runtime_manager import get_model_runtime_manager
from sqlalchemy import or_
from sqlalchemy.orm import Session

SCOPE_MODELS_READ = "models:read"
SCOPE_CHAT = "chat:write"
SCOPE_RESPONSES = "responses:write"
SCOPE_EMBEDDINGS = "embeddings:write"
SCOPE_VIDEOS = "videos:write"
SCOPE_AUDIO = "audio:write"
SCOPE_IMAGES = "images:write"
SCOPE_AGENTS = "agents:write"
SCOPE_KNOWLEDGE = "knowledge:read"
SCOPE_WORKFLOWS = "workflows:write"

DEFAULT_LOCAL_API_SCOPES = {
    SCOPE_MODELS_READ,
    SCOPE_CHAT,
    SCOPE_RESPONSES,
    SCOPE_EMBEDDINGS,
    SCOPE_VIDEOS,
    SCOPE_AUDIO,
    SCOPE_IMAGES,
    SCOPE_AGENTS,
    SCOPE_KNOWLEDGE,
    SCOPE_WORKFLOWS,
}


class LocalApiError(ValueError):
    """Stable, OpenAI-shaped failure for the local /v1 API."""

    def __init__(self, status_code: int, code: str, message: str, *, param: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.param = param


@dataclass(frozen=True)
class LocalApiPrincipal:
    user_id: int
    key_id: str
    key_prefix: str
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise LocalApiError(403, "API_KEY_SCOPE_DENIED", "The API key is missing the required scope.", param="Authorization")


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def _id() -> str:
    return uuid.uuid4().hex


def _key_hash(raw_key: str) -> str:
    return hmac.new(settings.jwt_secret.encode("utf-8"), raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def _parse_json_list(value: str | None) -> list[str]:
    try:
        payload = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if str(item).strip()]


def _json_list(values: Iterable[str]) -> str:
    return json.dumps(sorted({str(value).strip() for value in values if str(value).strip()}), ensure_ascii=False)


def openai_error_payload(code: str, message: str, correlation: str, *, param: str | None = None, error_type: str = "invalid_request_error") -> dict:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "code": code,
            "param": param,
        },
        "correlation_id": correlation,
    }


def authenticate_local_api_key(
    db: Session,
    authorization: str | None,
    *,
    required_scope: str | None = None,
) -> LocalApiPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise LocalApiError(401, "API_KEY_REQUIRED", "A ModelForge API key is required in Authorization: Bearer.", param="Authorization")
    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key.startswith("mf-"):
        raise LocalApiError(401, "API_KEY_INVALID", "The supplied bearer token is not a ModelForge API key.", param="Authorization")
    parts = raw_key.split("-", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        raise LocalApiError(401, "API_KEY_INVALID", "The supplied API key is malformed.", param="Authorization")
    prefix = f"mf-{parts[1]}"
    key = db.query(LocalApiKey).filter(LocalApiKey.prefix == prefix).first()
    if key is None or not hmac.compare_digest(key.secret_hash, _key_hash(raw_key)):
        raise LocalApiError(401, "API_KEY_INVALID", "The supplied API key is invalid.", param="Authorization")
    if key.revoked_at is not None:
        raise LocalApiError(401, "API_KEY_REVOKED", "The supplied API key has been revoked.", param="Authorization")
    if not key.enabled:
        raise LocalApiError(403, "API_KEY_DISABLED", "The supplied API key is disabled.", param="Authorization")
    if key.expires_at is not None and key.expires_at <= _now():
        raise LocalApiError(401, "API_KEY_EXPIRED", "The supplied API key has expired.", param="Authorization")
    setting = db.get(LocalApiSetting, key.user_id)
    if setting is not None and not setting.enabled:
        raise LocalApiError(503, "LOCAL_API_DISABLED", "The local OpenAI-compatible API is disabled.")
    scopes = frozenset(_parse_json_list(key.scopes_json))
    principal = LocalApiPrincipal(user_id=key.user_id, key_id=key.id, key_prefix=key.prefix, scopes=scopes)
    if required_scope:
        principal.require(required_scope)
    key.last_used_at = _now()
    db.commit()
    return principal


def require_local_api_key(scope: str | None = None):
    def dependency(authorization: str | None = Header(default=None, alias="Authorization"), db: Session | None = None):
        # FastAPI will supply db through the wrapper dependencies in each router.
        if db is None:  # pragma: no cover - defensive misuse guard
            raise RuntimeError("database session is required")
        return authenticate_local_api_key(db, authorization, required_scope=scope)

    return dependency


class LocalApiService:
    """Control-plane operations for the desktop local API console."""

    def __init__(self, db: Session):
        self.db = db

    def settings_for_user(self, user_id: int) -> LocalApiSetting:
        row = self.db.get(LocalApiSetting, user_id)
        if row is None:
            row = LocalApiSetting(user_id=user_id)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def update_settings(self, user_id: int, payload: dict) -> dict:
        row = self.settings_for_user(user_id)
        for key in (
            "enabled",
            "host",
            "port",
            "max_concurrent_requests",
            "max_concurrent_requests_per_model",
            "queue_size",
            "request_timeout_seconds",
            "idle_unload_seconds",
            "max_upload_bytes",
            "auto_load_models",
            "allow_lan",
            "logging_enabled",
            "log_retention_days",
            "temp_dir",
        ):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])
        if "cors_origins" in payload and payload["cors_origins"] is not None:
            row.cors_origins_json = _json_list(payload["cors_origins"])
        self.db.commit()
        return self.status(user_id)

    def require_enabled(self, user_id: int) -> LocalApiSetting:
        row = self.settings_for_user(user_id)
        if not row.enabled:
            raise LocalApiError(503, "LOCAL_API_DISABLED", "The local OpenAI-compatible API is disabled.")
        return row

    def require_loaded_or_autoload(self, user_id: int, record: ModelRecord) -> None:
        row = self.require_enabled(user_id)
        runtime = get_model_runtime_manager().get_status(record.id)
        if runtime.get("active") or row.auto_load_models:
            return
        raise LocalApiError(409, "MODEL_NOT_LOADED", "Model is not loaded and automatic loading is disabled.", param="model")

    def issue_key(self, user_id: int, name: str, scopes: list[str] | None = None, expires_at: dt.datetime | None = None) -> tuple[LocalApiKey, str]:
        clean_name = name.strip()[:100]
        if not clean_name:
            raise LocalApiError(422, "API_KEY_NAME_REQUIRED", "API key name is required.", param="name")
        effective_scopes = set(scopes or DEFAULT_LOCAL_API_SCOPES) & DEFAULT_LOCAL_API_SCOPES
        if not effective_scopes:
            raise LocalApiError(422, "API_KEY_SCOPE_REQUIRED", "At least one valid API key scope is required.", param="scopes")
        for _ in range(20):
            prefix = "mf-" + secrets.token_hex(6)
            if self.db.query(LocalApiKey).filter(LocalApiKey.prefix == prefix).first() is None:
                break
        else:  # pragma: no cover - practically unreachable
            raise LocalApiError(500, "API_KEY_PREFIX_EXHAUSTED", "Could not allocate an API key prefix.")
        raw_key = f"{prefix}-{secrets.token_urlsafe(32)}"
        key = LocalApiKey(
            id=_id(),
            user_id=user_id,
            name=clean_name,
            prefix=prefix,
            secret_hash=_key_hash(raw_key),
            scopes_json=_json_list(effective_scopes),
            expires_at=expires_at,
        )
        self.db.add(key)
        self.db.commit()
        self.db.refresh(key)
        return key, raw_key

    def list_keys(self, user_id: int) -> list[dict]:
        keys = self.db.query(LocalApiKey).filter_by(user_id=user_id).order_by(LocalApiKey.created_at.desc()).all()
        return [key.to_dict() for key in keys]

    def set_key_enabled(self, user_id: int, key_id: str, enabled: bool) -> dict:
        key = self._require_key(user_id, key_id)
        key.enabled = bool(enabled)
        self.db.commit()
        return key.to_dict()

    def revoke_key(self, user_id: int, key_id: str) -> dict:
        key = self._require_key(user_id, key_id)
        if key.revoked_at is None:
            key.revoked_at = _now()
            key.enabled = False
            self.db.commit()
        return key.to_dict()

    def _require_key(self, user_id: int, key_id: str) -> LocalApiKey:
        key = self.db.query(LocalApiKey).filter_by(user_id=user_id, id=key_id).first()
        if key is None:
            raise LocalApiError(404, "API_KEY_NOT_FOUND", "API key was not found.")
        return key

    def resolve_model(self, user_id: int, reference: str | int | None) -> ModelRecord | None:
        if reference is None:
            return None
        text = str(reference).strip()
        if text:
            alias = (
                self.db.query(ModelApiAlias)
                .filter_by(user_id=user_id, alias=text, enabled=True)
                .first()
            )
            if alias is not None:
                return ModelRegistry(self.db).get(alias.model_id, user_id)
        return ModelResolver(self.db).resolve(reference, user_id)

    def require_model(self, user_id: int, reference: str | int | None, *, capability: str | None = None) -> ModelRecord:
        record = self.resolve_model(user_id, reference)
        if record is None:
            raise LocalApiError(404, "MODEL_NOT_FOUND", "Model was not found or is not visible to this API key.", param="model")
        registry = ModelRegistry(self.db)
        if capability and not registry.supports(record, capability):
            raise LocalApiError(422, "MODEL_CAPABILITY_UNSUPPORTED", "Model does not support the requested API endpoint.", param="model")
        return record

    def set_alias(self, user_id: int, model_id: int, alias: str | None) -> dict:
        record = ModelRegistry(self.db).require(model_id, user_id)
        clean = (alias or "").strip()
        existing = self.db.query(ModelApiAlias).filter_by(user_id=user_id, model_id=record.id).first()
        if not clean:
            if existing is not None:
                self.db.delete(existing)
                self.db.commit()
            return self.model_descriptor(user_id, record)
        duplicate = self.db.query(ModelApiAlias).filter_by(user_id=user_id, alias=clean).first()
        if duplicate is not None and duplicate.model_id != record.id:
            raise LocalApiError(409, "MODEL_ALIAS_CONFLICT", "API model alias is already in use.", param="alias")
        if existing is None:
            existing = ModelApiAlias(id=_id(), user_id=user_id, model_id=record.id, alias=clean)
            self.db.add(existing)
        else:
            existing.alias = clean
            existing.enabled = True
        self.db.commit()
        return self.model_descriptor(user_id, record)

    def model_descriptor(self, user_id: int, record: ModelRecord) -> dict:
        registry = ModelRegistry(self.db)
        alias = self.db.query(ModelApiAlias).filter_by(user_id=user_id, model_id=record.id, enabled=True).first()
        caps = registry.capabilities(record)
        runtime = get_model_runtime_manager().get_status(record.id)
        endpoints = _endpoints_for_caps(caps)
        compatibility = _compatibility_for_record(record, caps, bool(runtime.get("active")))
        api_id = alias.alias if alias else record.name
        return {
            "id": api_id,
            "object": "model",
            "owned_by": "modelforge",
            "model_id": record.id,
            "name": record.name,
            "display_name": record.display_name or record.name,
            "alias": alias.alias if alias else None,
            "format": record.format,
            "quant": record.quant,
            "size_bytes": record.size_bytes,
            "path": record.path,
            "capabilities": caps,
            "api_capabilities": _api_capabilities_for_caps(caps),
            "endpoints": endpoints,
            "ready": registry.is_ready(record),
            "loaded": bool(runtime.get("active")),
            "runtime_status": runtime.get("status"),
            "compatibility": compatibility,
            "metadata": record.metadata_dict(),
            "created": int((record.created_time or _now()).timestamp()),
        }

    def list_model_descriptors(self, user_id: int) -> list[dict]:
        registry = ModelRegistry(self.db)
        return [self.model_descriptor(user_id, record) for record in registry.list_models(user_id)]

    def status(self, user_id: int) -> dict:
        row = self.settings_for_user(user_id)
        logs = self.list_logs(user_id, limit=20)
        loaded = get_model_runtime_manager().instances_payload()
        model_root = Path(settings.model_path)
        disk = _disk_payload(model_root)
        total_requests = self.db.query(LocalApiRequestLog).filter_by(user_id=user_id).count()
        error_requests = self.db.query(LocalApiRequestLog).filter(LocalApiRequestLog.user_id == user_id, LocalApiRequestLog.status_code >= 400).count()
        return {
            "enabled": bool(row.enabled),
            "service_state": "running" if row.enabled else "stopped",
            "host": row.host,
            "port": row.port,
            "base_url": f"http://{row.host}:{row.port}/v1",
            "cors_origins": _parse_json_list(row.cors_origins_json),
            "max_concurrent_requests": row.max_concurrent_requests,
            "max_concurrent_requests_per_model": row.max_concurrent_requests_per_model,
            "queue_size": row.queue_size,
            "request_timeout_seconds": row.request_timeout_seconds,
            "idle_unload_seconds": row.idle_unload_seconds,
            "max_upload_bytes": row.max_upload_bytes,
            "auto_load_models": bool(row.auto_load_models),
            "allow_lan": bool(row.allow_lan),
            "logging_enabled": bool(row.logging_enabled),
            "log_retention_days": row.log_retention_days,
            "temp_dir": row.temp_dir,
            "loaded_models": len([item for item in loaded if item.get("active")]),
            "active_requests": sum(int(item.get("active_requests") or 0) for item in loaded),
            "request_count": total_requests,
            "error_count": error_requests,
            "disk": disk,
            "recent_logs": logs,
        }

    def list_logs(self, user_id: int, limit: int = 100) -> list[dict]:
        rows = (
            self.db.query(LocalApiRequestLog)
            .filter_by(user_id=user_id)
            .order_by(LocalApiRequestLog.created_at.desc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
        return [row.to_dict() for row in rows]

    def clear_logs(self, user_id: int) -> dict:
        deleted = self.db.query(LocalApiRequestLog).filter_by(user_id=user_id).delete()
        self.db.commit()
        return {"deleted": int(deleted)}

    def record_request(
        self,
        principal: LocalApiPrincipal,
        *,
        request_id: str,
        endpoint: str,
        method: str,
        model: str | None,
        status_code: int,
        duration_ms: int,
        error_code: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        row_settings = self.settings_for_user(principal.user_id)
        if not row_settings.logging_enabled:
            return
        row = LocalApiRequestLog(
            id=_id(),
            user_id=principal.user_id,
            api_key_id=principal.key_id,
            key_prefix=principal.key_prefix,
            request_id=request_id[:96],
            endpoint=endpoint[:128],
            method=method[:10],
            model=(model or None),
            status_code=int(status_code),
            duration_ms=max(0, int(duration_ms)),
            error_code=error_code,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self.db.add(row)
        self.db.commit()


def _api_capabilities_for_caps(caps: list[str]) -> list[str]:
    result: list[str] = []
    if ModelCapability.CHAT.value in caps or ModelCapability.INFERENCE.value in caps:
        result.extend(["text-generation", "chat-completions", "responses"])
    if ModelCapability.EMBEDDING.value in caps:
        result.append("embeddings")
    if ModelCapability.VISION.value in caps:
        result.append("image-understanding")
    if ModelCapability.AUDIO.value in caps:
        result.append("audio")
    if ModelCapability.IMAGE.value in caps:
        result.append("image-generation")
    return sorted(set(result))


def _endpoints_for_caps(caps: list[str]) -> list[str]:
    endpoints = ["/v1/models"]
    if ModelCapability.CHAT.value in caps or ModelCapability.INFERENCE.value in caps:
        endpoints.extend(["/v1/chat/completions", "/v1/responses"])
    if ModelCapability.EMBEDDING.value in caps:
        endpoints.append("/v1/embeddings")
    if ModelCapability.AUDIO.value in caps:
        endpoints.append("/v1/audio/transcriptions")
    if ModelCapability.IMAGE.value in caps:
        endpoints.append("/v1/images/generations")
    return endpoints


def _compatibility_for_record(record: ModelRecord, caps: list[str], loaded: bool) -> dict:
    runtimes = record.supported_runtime_list()
    supported = bool(runtimes or record.preferred_runtime or (record.format or "").lower() in {"gguf", "ggml", "safetensors", "transformers", "pytorch"})
    reasons: list[str] = []
    if not supported:
        reasons.append("No local runtime adapter is registered for this model format.")
    if ModelCapability.EMBEDDING.value in caps and not loaded:
        reasons.append("Embedding requests use the configured embedding backend until this model is explicitly supported.")
    return {
        "downloadable": True,
        "runnable": supported and bool(set(caps) & {ModelCapability.CHAT.value, ModelCapability.INFERENCE.value, ModelCapability.EMBEDDING.value}),
        "loaded": loaded,
        "state": "loaded" if loaded else ("supported" if supported else "download_only"),
        "reasons": reasons,
    }


def _disk_payload(path: Path) -> dict:
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        return {"path": str(path), "total_bytes": usage.total, "free_bytes": usage.free, "used_bytes": usage.used}
    except OSError:
        return {"path": str(path), "total_bytes": None, "free_bytes": None, "used_bytes": None}
