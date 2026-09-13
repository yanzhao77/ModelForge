"""Model management API routes backed by the unified model registry."""

from typing import Literal

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from models.records import User, UserModelPreference
from pydantic import BaseModel, Field
from services.audit_log import record_operation
from services.downloader import downloader
from services.model_capabilities import CapabilityFilter
from services.model_manager import ModelManager
from services.model_readiness_service import ModelReadinessError, ModelReadinessService
from services.model_registry import ModelRegistry, ModelRegistryError
from services.model_runtime_manager import ModelRuntimeError, get_model_runtime_manager
from services.resource_lease import ResourceBusy, inference_lease
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/models", tags=["models"])


class ScanRequest(BaseModel):
    path: str | None = Field(default=None, max_length=2048)


class InstallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(default="local", min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=2048)
    size: str = Field(default="", max_length=64)
    format: str | None = Field(default=None, max_length=64)
    quant: str | None = Field(default=None, max_length=64)


class DownloadRequest(BaseModel):
    repo_id: str = Field(min_length=1, max_length=255)
    filename: str | None = Field(default=None, max_length=512)


class DefaultModelRequest(BaseModel):
    kind: Literal["local", "remote"]
    model_ref: str = Field(min_length=1, max_length=255)
    provider_id: int | None = None
    request_id: str | None = Field(default=None, max_length=64)


class LoadModelRequest(BaseModel):
    """Optional runtime overrides for one model load."""

    context_length: int | None = Field(default=None, ge=1, le=1_048_576)
    gpu_layers: int | None = Field(default=None, ge=-1, le=4096)
    threads: int | None = Field(default=None, ge=0, le=1024)


def _manager(db: DBSession) -> ModelManager:
    return ModelManager(db)


def _readiness(db: DBSession) -> ModelReadinessService:
    return ModelReadinessService(db)


def _registry(db: DBSession) -> ModelRegistry:
    return ModelRegistry(db)


def _model_payload(record, registry: ModelRegistry) -> dict:
    """One model as the registry sees it, plus its live runtime status."""
    payload = record.to_dict()
    payload["capabilities"] = registry.capabilities(record)
    payload["ready"] = registry.is_ready(record)
    payload["runtime_status"] = _runtime_status_for(record.id)
    return payload


def _runtime_status_for(model_id: int) -> str:
    instance = get_model_runtime_manager().get_current()
    if instance is None:
        return "idle"
    return instance.status if instance.model_id == model_id else "idle"


def _registry_problem(exc: Exception, corr: str):
    """Translate a registry/runtime failure into its stable problem contract."""
    return problem(exc.http_status, exc.code, exc.message, details=exc.details or None, correlation=corr)


@router.get("")
def list_models(
    capability: str | None = None,
    status: str | None = None,
    format: str | None = None,
    source: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List model assets, optionally filtered by capability/status/format/source."""
    try:
        capability_value = CapabilityFilter.parse(capability)
    except ValueError as exc:
        raise problem(
            400,
            "MODEL_CAPABILITY_INVALID",
            "Unknown model capability filter.",
            correlation=correlation_id(),
        ) from exc
    registry = _registry(db)
    records = registry.list_models(
        user.id,
        capability=capability_value,
        status=status,
        model_format=format,
        source=source,
    )
    return [_model_payload(record, registry) for record in records]


@router.post("/scan")
def scan_models(
    req: ScanRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        models = _manager(db).scan(req.path, user.id)
    except ValueError as exc:
        raise problem(403, "MODEL_PATH_OUTSIDE_ALLOWED_ROOT", "Model path is outside the configured model root.", correlation=correlation_id()) from exc
    registry = _registry(db)
    for model in models:
        registry.refresh(model, commit=False)
    db.commit()
    return [_model_payload(model, registry) for model in models]


@router.post("/install")
def install_model(
    req: InstallRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        model = _registry(db).register(
            name=req.name,
            provider=req.provider,
            path=req.path,
            size=req.size,
            user_id=user.id,
            model_format=req.format,
            quant=req.quant,
        )
    except ModelRegistryError as exc:
        raise _registry_problem(exc, correlation_id()) from exc
    except ValueError as exc:
        raise problem(403, "MODEL_PATH_OUTSIDE_ALLOWED_ROOT", "Model path is outside the configured model root.", correlation=correlation_id()) from exc
    return model.to_dict()


@router.get("/search")
def search_hf_models(
    q: str = "", author: str | None = None, limit: int = 20,
    user: User = Depends(get_current_user),
):
    try:
        return downloader.search_hf(q, author, limit)
    except Exception as exc:
        raise problem(502, "MODEL_SEARCH_UNAVAILABLE", "Model search is temporarily unavailable.", correlation=correlation_id()) from exc


@router.post("/download")
def download_model(
    req: DownloadRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.start(req.repo_id, user.id, req.filename, db=db)
    return task.to_dict()


@router.get("/download/{task_id}")
def download_status(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.get(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return task.to_dict()


@router.post("/download/{task_id}/pause")
def pause_download(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.pause(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return task.to_dict()


@router.post("/download/{task_id}/resume")
def resume_download(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.resume(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return task.to_dict()


@router.post("/download/{task_id}/restart")
def restart_download(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.restart(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return task.to_dict()


@router.get("/readiness")
def model_readiness(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Return a user-scoped, credential-safe model availability snapshot."""
    return _readiness(db).snapshot(user.id)


@router.put("/default")
def set_default_model(
    req: DefaultModelRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = req.request_id or correlation_id()
    try:
        result = _readiness(db).set_default(
            user.id,
            kind=req.kind,
            model_ref=req.model_ref,
            provider_id=req.provider_id,
            commit=False,
        )
    except ModelReadinessError as exc:
        raise problem(400, "MODEL_DEFAULT_INVALID", "Selected default model is not available", correlation=corr) from exc
    try:
        record_operation(db, user_id=user.id, action="model.default.set", object_type="model_default", object_id=req.model_ref, correlation_id=corr, metadata={"kind": req.kind, "provider_id": req.provider_id})
        db.commit()
    except Exception as exc:
        db.rollback()
        raise problem(500, "MODEL_DEFAULT_PERSIST_FAILED", "Default model could not be persisted", correlation=corr) from exc
    return operation_result(result, corr)


@router.delete("/default")
def clear_default_model(
    request_id: str | None = None, db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    corr = request_id or correlation_id()
    result = _readiness(db).clear_default(user.id, commit=False)
    try:
        record_operation(db, user_id=user.id, action="model.default.clear", object_type="model_default", object_id=str(user.id), correlation_id=corr)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise problem(500, "MODEL_DEFAULT_PERSIST_FAILED", "Default model could not be persisted", correlation=corr) from exc
    return operation_result(result, corr)


@router.get("/default")
def get_default_model(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Return the user's preferred default model (independent of what is loaded)."""
    registry = _registry(db)
    record = registry.default_model(user.id)
    if record is None:
        return {"model_id": None, "model": None}
    return {"model_id": record.id, "model": _model_payload(record, registry)}


@router.post("/{model_id}/default")
def set_model_default(
    model_id: int, db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Mark a local model as this user's default (does not load it)."""
    corr = correlation_id()
    registry = _registry(db)
    try:
        record = registry.set_default(user.id, model_id)
    except ModelRegistryError as exc:
        raise _registry_problem(exc, corr) from exc
    record_operation(db, user_id=user.id, action="model.default.set", object_type="model_default", object_id=str(model_id), correlation_id=corr, metadata={"kind": "local"})
    db.commit()
    return operation_result(_model_payload(record, registry), corr)


@router.get("/{model_id}/runtime")
def model_runtime_status(
    model_id: int, db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Live runtime instance status for one model."""
    try:
        _registry(db).require(model_id, user.id)
    except ModelRegistryError as exc:
        raise _registry_problem(exc, correlation_id()) from exc
    return get_model_runtime_manager().get_status(model_id)


@router.post("/{model_id}/load")
async def load_model(
    model_id: int,
    req: LoadModelRequest | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Load a registry model into the shared local runtime.

    Inference is exclusive across accounts, so the machine-wide lease is taken
    for the load operation; the owning account keeps the runtime afterwards,
    exactly like an explicit ``/runtime/start``.
    """
    corr = correlation_id()
    options = req or LoadModelRequest()
    try:
        lease_handle = inference_lease.acquire(user_id=user.id, username=user.username)
    except ResourceBusy as exc:
        raise exc.to_problem(corr) from exc
    try:
        instance = await get_model_runtime_manager().load(
            model_id,
            user.id,
            db=db,
            context_length=options.context_length,
            gpu_layers=options.gpu_layers,
            threads=options.threads,
        )
    except ModelRuntimeError as exc:
        # Only a lease this request created is released: re-entrant loads by the
        # owning account must not drop an explicitly held runtime.
        if lease_handle.created:
            lease_handle.release()
        raise _registry_problem(exc, corr) from exc
    return instance.to_dict()


@router.post("/{model_id}/unload")
async def unload_model(
    model_id: int, db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        _registry(db).require(model_id, user.id)
    except ModelRegistryError as exc:
        raise _registry_problem(exc, corr) from exc
    try:
        result = await get_model_runtime_manager().unload(model_id, user.id, db=db)
    except ModelRuntimeError as exc:
        raise _registry_problem(exc, corr) from exc
    from services.resource_lease import inference_holder

    holder = inference_holder()
    if holder is not None and holder["user_id"] == user.id:
        inference_lease.release(user_id=user.id)
    return result


@router.get("/{model_id}")
def get_model(
    model_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    registry = _registry(db)
    model = registry.get(model_id, user.id)
    if model is None:
        raise problem(404, "LOCAL_MODEL_NOT_FOUND", "Local model record was not found.")
    registry.refresh(model, commit=True)
    return _model_payload(model, registry)


@router.delete("/{model_id}")
def remove_model(
    model_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = get_model_runtime_manager().get_current()
    if instance is not None and instance.model_id == model_id:
        raise problem(
            409,
            "MODEL_ALREADY_LOADED",
            "模型正在运行，请先卸载后再删除。",
            correlation=correlation_id(),
        )
    ok = _manager(db).remove(model_id, user.id)
    if not ok:
        raise problem(404, "LOCAL_MODEL_NOT_FOUND", "Local model record was not found.")
    # A deleted default model must not leave a dangling preference behind.
    preference = db.get(UserModelPreference, user.id)
    if (
        preference is not None
        and preference.default_kind == "local"
        and preference.default_model_ref == str(model_id)
    ):
        db.delete(preference)
        db.commit()
    return {"ok": True}
