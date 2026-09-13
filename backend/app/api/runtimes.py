"""Runtime inventory + health API (V1.2).

`GET /api/v1/runtimes` answers "which inference backends does this install
have, and are they usable?", and `/{id}/health` gives the per-adapter detail
(dependency present, models that fit it, whether it is currently loaded).

Health is computed from local state only — no network probes — so it is safe to
poll from the desktop.
"""

from __future__ import annotations

from core.api_contracts import correlation_id, problem
from core.config import settings
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends
from models.records import RemoteProviderConfig, User
from services.model_capabilities import ModelCapability
from services.model_registry import ModelRegistry
from services.model_runtime_manager import get_model_runtime_manager
from services.runtime_resolver import RuntimeResolver
from services.runtimes.adapters import OLLAMA, REMOTE_OPENAI
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/runtimes", tags=["runtimes"])


def _local_adapter_models(db: DBSession, user_id: int, adapter) -> list[dict]:
    registry = ModelRegistry(db)
    records = registry.list_models(user_id, capability=ModelCapability.INFERENCE.value)
    return [record for record in records if adapter.supports_model(record)]


def _remote_provider_count(db: DBSession, user_id: int) -> int:
    return (
        db.query(RemoteProviderConfig)
        .filter(
            RemoteProviderConfig.user_id == user_id,
            RemoteProviderConfig.enabled.is_(True),
            RemoteProviderConfig.verification_status == "success",
        )
        .count()
    )


def _health(db: DBSession, user_id: int, adapter) -> dict:
    checks: list[dict] = []
    dependency_ok = adapter.dependency_available()
    if adapter.requires_dependency:
        checks.append(
            {
                "name": "dependency",
                "ok": dependency_ok,
                "detail": ", ".join(adapter.requires_dependency),
            }
        )
    if adapter.id == OLLAMA:
        configured = bool((settings.ollama_base_url or "").strip())
        checks.append({"name": "endpoint", "ok": configured, "detail": settings.ollama_base_url})
        dependency_ok = dependency_ok and configured
    models: list[dict] = []
    if adapter.id == REMOTE_OPENAI:
        provider_count = _remote_provider_count(db, user_id)
        checks.append({"name": "providers", "ok": provider_count > 0, "detail": str(provider_count)})
        dependency_ok = provider_count > 0
    else:
        models = _local_adapter_models(db, user_id, adapter)
        checks.append({"name": "models", "ok": bool(models), "detail": str(len(models))})

    manager = get_model_runtime_manager()
    instance = manager.get_current()
    loaded = bool(instance is not None and instance.runtime_id == adapter.id)
    if loaded:
        checks.append({"name": "loaded", "ok": True, "detail": instance.model_name})

    if not adapter.local:
        status = "available" if dependency_ok else "unconfigured"
    elif dependency_ok:
        status = "loaded" if loaded else "available"
    else:
        status = "unavailable"
    return {
        "id": adapter.id,
        "label": adapter.label,
        "local": adapter.local,
        "capabilities": sorted(adapter.capabilities),
        "description": adapter.description,
        "requires": list(adapter.requires_dependency),
        "status": status,
        "loaded": loaded,
        "model_count": len(models),
        "models": [
            {"model_id": record.id, "name": record.name, "format": record.format}
            for record in models[:50]
        ],
        "checks": checks,
    }


@router.get("")
def list_runtimes(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    manager = get_model_runtime_manager()
    return {
        "runtimes": [_health(db, user.id, adapter) for adapter in RuntimeResolver.catalog()],
        "active": manager.get_current().to_dict() if manager.get_current() else None,
        "recent_events": manager.recent_events(),
    }


@router.get("/{runtime_id}/health")
def runtime_health(
    runtime_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    adapter = RuntimeResolver.adapter(runtime_id)
    if adapter is None:
        raise problem(
            404,
            "RUNTIME_NOT_FOUND",
            "Unknown runtime adapter.",
            correlation=correlation_id(),
            details={"runtime_id": runtime_id},
        )
    return _health(db, user.id, adapter)
