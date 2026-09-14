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
from services.local_model_importer import (
    LocalModelDetector,
    LocalModelImportError,
    validate_manual_capabilities,
)
from services.model_capabilities import CapabilityFilter, ModelCapability
from services.model_capability_registry import video_spec_from_record
from services.model_catalog import CatalogQuery, ModelCatalogService, parse_hf_repo_id
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
    files: list[str] = Field(default_factory=list, max_length=128)
    include_support_files: bool = True
    full_repository: bool = False


class ModelCatalogSearchRequest(BaseModel):
    q: str = Field(default="", max_length=255)
    category: str = Field(default="all", max_length=64)
    format: str | None = Field(default=None, max_length=64)
    library: str | None = Field(default=None, max_length=64)
    author: str | None = Field(default=None, max_length=255)
    gated: bool | None = None
    compatible: bool | None = None
    sort: str = Field(default="relevance", max_length=64)
    limit: int = Field(default=30, ge=1, le=100)


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
    #: V1.2: force one adapter (llama_cpp / transformers). Must be supported by
    #: the asset, otherwise the load is rejected.
    runtime: str | None = Field(default=None, max_length=64)


class LocalModelDetectRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class LocalModelRegisterRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    capabilities: list[str] | None = Field(default=None, max_length=16)
    preferred_runtime: str | None = Field(default=None, max_length=64)
    load: bool = False
    context_length: int | None = Field(default=None, ge=1, le=1_048_576)
    gpu_layers: int | None = Field(default=None, ge=-1, le=4096)
    threads: int | None = Field(default=None, ge=0, le=1024)


def _manager(db: DBSession) -> ModelManager:
    return ModelManager(db)


def _readiness(db: DBSession) -> ModelReadinessService:
    return ModelReadinessService(db)


def _registry(db: DBSession) -> ModelRegistry:
    return ModelRegistry(db)


def _catalog() -> ModelCatalogService:
    return ModelCatalogService()


def _model_payload(record, registry: ModelRegistry) -> dict:
    """One model as the registry sees it, plus its live runtime status."""
    payload = record.to_dict()
    payload["capabilities"] = registry.capabilities(record)
    payload["ready"] = registry.is_ready(record)
    payload["runtime_status"] = _runtime_status_for(record.id)
    if payload.get("status") == "loaded" and payload["runtime_status"] != "loaded":
        payload["status"] = "ready"
    return payload


def _runtime_status_for(model_id: int) -> str:
    instance = get_model_runtime_manager().get_current()
    if instance is None:
        return "idle"
    return instance.status if instance.model_id == model_id else "idle"


def _registry_problem(exc: Exception, corr: str):
    """Translate a registry/runtime failure into its stable problem contract."""
    return problem(exc.http_status, exc.code, exc.message, details=exc.details or None, correlation=corr)


def _local_import_problem(exc: LocalModelImportError, corr: str):
    return problem(exc.http_status, exc.code, exc.message, details=exc.details or None, correlation=corr)


def _operation_descriptors(record, registry: ModelRegistry) -> dict:
    caps = registry.capabilities(record)
    runtime = get_model_runtime_manager().get_status(record.id)
    model_ref = record.display_name or record.name
    operations: list[dict] = []
    api_examples: dict[str, str] = {}
    if ModelCapability.CHAT.value in caps or ModelCapability.INFERENCE.value in caps:
        operations.append(
            {
                "id": "chat",
                "label": "Chat / text generation",
                "available": bool(runtime.get("active")) and runtime.get("model_id") == record.id,
                "endpoints": ["/v1/chat/completions", "/v1/responses"],
                "example": {"model": model_ref, "messages": [{"role": "user", "content": "Hello"}]},
                "constraints": {"streaming": True, "max_messages": 100},
            }
        )
        api_examples["chat"] = f"curl -X POST /v1/chat/completions -H 'Authorization: Bearer $MF_API_KEY' -d '{{\"model\":\"{model_ref}\",\"messages\":[{{\"role\":\"user\",\"content\":\"Hello\"}}]}}'"
    if ModelCapability.EMBEDDING.value in caps:
        operations.append(
            {
                "id": "embeddings",
                "label": "Embeddings",
                "available": bool(runtime.get("active")) and runtime.get("model_id") == record.id,
                "endpoints": ["/v1/embeddings"],
                "example": {"model": model_ref, "input": ["hello", "world"]},
                "constraints": {"max_inputs": 64},
            }
        )
        api_examples["embeddings"] = f"curl -X POST /v1/embeddings -H 'Authorization: Bearer $MF_API_KEY' -d '{{\"model\":\"{model_ref}\",\"input\":[\"hello\"]}}'"
    if ModelCapability.VIDEO.value in caps:
        video_spec = video_spec_from_record(record)
        local_import = (record.metadata_dict().get("local_import") or {}) if isinstance(record.metadata_dict(), dict) else {}
        load_validation = local_import.get("load_validation") if isinstance(local_import, dict) else None
        load_failed = isinstance(load_validation, dict) and load_validation.get("status") == "failed"
        available = bool(local_import.get("runnable") and video_spec is not None and not load_failed)
        profiles = []
        if video_spec is not None:
            profiles = [
                {
                    "id": profile.profile_id,
                    "seconds": profile.seconds,
                    "fps": profile.fps,
                    "size": profile.size,
                    "frames": profile.frames,
                    "default_steps": profile.default_steps,
                    "min_steps": profile.min_steps,
                    "max_steps": profile.max_steps,
                }
                for profile in video_spec.profiles
            ]
        reason = None if available else str((load_validation or {}).get("message") if isinstance(load_validation, dict) else "") or "; ".join(local_import.get("unavailable_reasons") or ["Wan video runtime is not ready."])
        operation = {
            "id": "video-generation",
            "label": "Text to video",
            "available": available,
            "endpoints": ["/v1/videos", "/api/v1/videos"] if available else [],
            "constraints": {"profiles": profiles},
            "unavailable_reason": reason,
        }
        if available:
            operation["example"] = {"model": f"local:{record.id}", "prompt": "A short cinematic test clip", "seconds": 1, "fps": 4, "size": "256x256"}
            api_examples["videos"] = f"curl -X POST /v1/videos -H 'Authorization: Bearer $MF_API_KEY' -d '{{\"model\":\"local:{record.id}\",\"prompt\":\"A short cinematic test clip\",\"seconds\":1,\"fps\":4,\"size\":\"256x256\"}}'"
        operations.append(operation)
    unavailable_map = {
        ModelCapability.RERANKER.value: ("rerank", "Reranker runtime is not connected in this build."),
        ModelCapability.IMAGE.value: ("image-generation", "Image generation runtime is not connected in this build."),
        ModelCapability.ASR.value: ("speech-to-text", "Audio transcription runtime is not connected in this build."),
        ModelCapability.TTS.value: ("text-to-speech", "Speech synthesis runtime is not connected in this build."),
    }
    for cap, (operation_id, reason) in unavailable_map.items():
        if cap in caps:
            operations.append({"id": operation_id, "available": False, "unavailable_reason": reason, "endpoints": []})
    return {
        "model_id": record.id,
        "model": _model_payload(record, registry),
        "runtime": runtime,
        "operations": operations,
        "api_examples": api_examples,
    }


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
    payload = [_model_payload(record, registry) for record in records]
    # V1.2: remote providers are part of the same inventory (source=remote).
    if source in (None, "", "remote") and format in (None, "", "remote_openai"):
        remote = registry.remote_model_descriptors(user.id)
        if capability_value:
            remote = [item for item in remote if capability_value in item["capabilities"]]
        payload.extend(remote)
    return payload


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


@router.post("/local/detect")
def detect_local_model(
    req: LocalModelDetectRequest,
    user: User = Depends(get_current_user),  # noqa: ARG001 - auth scopes local path probing
):
    """Inspect a user-selected local model path without registering it."""
    corr = correlation_id()
    try:
        return LocalModelDetector().detect(req.path).payload
    except LocalModelImportError as exc:
        raise _local_import_problem(exc, corr) from exc


@router.post("/local/register")
async def register_local_model(
    req: LocalModelRegisterRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Register a local model by reference; optionally load it immediately."""
    corr = correlation_id()
    registry = _registry(db)
    try:
        detection = LocalModelDetector().detect(req.path).payload
        capabilities = validate_manual_capabilities(detection, req.capabilities)
        record = registry.register_detected_local(
            detection=detection,
            user_id=user.id,
            name=req.name,
            display_name=req.display_name,
            capabilities=capabilities,
            preferred_runtime=req.preferred_runtime,
            load_after_register=req.load,
            commit=False,
        )
        record_operation(
            db,
            user_id=user.id,
            action="model.local.register",
            object_type="model",
            object_id=str(record.id),
            correlation_id=corr,
            metadata={"path": detection.get("real_path"), "capabilities": capabilities, "load": req.load},
        )
        db.commit()
    except LocalModelImportError as exc:
        db.rollback()
        raise _local_import_problem(exc, corr) from exc
    except ModelRegistryError as exc:
        db.rollback()
        raise _registry_problem(exc, corr) from exc
    payload = {"model": _model_payload(record, registry), "detection": detection, "loaded": None}
    if req.load:
        try:
            lease_handle = inference_lease.acquire(user_id=user.id, username=user.username)
        except ResourceBusy as exc:
            payload["loaded"] = {"ok": False, "error": exc.lease.code, "message": exc.lease.message}
            return payload
        try:
            instance = await get_model_runtime_manager().load(
                record.id,
                user.id,
                db=db,
                runtime=req.preferred_runtime,
                context_length=req.context_length,
                gpu_layers=req.gpu_layers,
                threads=req.threads,
            )
            payload["loaded"] = {"ok": True, "instance": instance.to_dict()}
        except ModelRuntimeError as exc:
            if lease_handle.created:
                lease_handle.release()
            payload["loaded"] = {"ok": False, "error": exc.code, "message": exc.message, "details": exc.details}
        return payload
    return payload


@router.get("/{model_id}/operations")
def model_operations(
    model_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    registry = _registry(db)
    try:
        record = registry.require(model_id, user.id)
    except ModelRegistryError as exc:
        raise _registry_problem(exc, correlation_id()) from exc
    return _operation_descriptors(record, registry)


@router.get("/search")
def search_hf_models(
    q: str = "", author: str | None = None, limit: int = 20,
    user: User = Depends(get_current_user),
):
    try:
        return downloader.search_hf(q, author, limit)
    except Exception as exc:
        raise problem(502, "MODEL_SEARCH_UNAVAILABLE", "Model search is temporarily unavailable.", correlation=correlation_id()) from exc


@router.get("/catalog/search")
def search_model_catalog(
    q: str = "",
    category: str = "all",
    format: str | None = None,
    library: str | None = None,
    author: str | None = None,
    gated: bool | None = None,
    compatible: bool | None = None,
    sort: str = "relevance",
    limit: int = 30,
    user: User = Depends(get_current_user),  # noqa: ARG001 - user scopes future sources
):
    try:
        query = CatalogQuery(
            query=q,
            category=category or "all",
            model_format=format,
            library=library,
            author=author,
            gated=gated,
            compatible=compatible,
            sort=sort,
            limit=limit,
        )
        return {"models": _catalog().search(query)}
    except Exception as exc:
        raise problem(502, "MODEL_CATALOG_SEARCH_UNAVAILABLE", "Model catalog search is temporarily unavailable.", correlation=correlation_id()) from exc


@router.get("/catalog/{repo_id:path}")
def model_catalog_detail(
    repo_id: str,
    source: str = "huggingface",
    user: User = Depends(get_current_user),  # noqa: ARG001 - user scopes future sources
):
    try:
        detail = _catalog().detail(parse_hf_repo_id(repo_id), source=source)
        return detail
    except Exception as exc:
        raise problem(502, "MODEL_CATALOG_DETAIL_UNAVAILABLE", "Model repository metadata is temporarily unavailable.", correlation=correlation_id()) from exc


@router.post("/download")
def download_model(
    req: DownloadRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.start(
        parse_hf_repo_id(req.repo_id),
        user.id,
        req.filename,
        files=req.files,
        include_support_files=req.include_support_files,
        full_repository=req.full_repository,
        db=db,
    )
    return downloader.to_payload(task)


@router.get("/download")
def list_downloads(
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"tasks": [downloader.to_payload(task) for task in downloader.list(user.id, db=db)]}


@router.get("/download/{task_id}")
def download_status(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.get(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return downloader.to_payload(task)


@router.post("/download/{task_id}/pause")
def pause_download(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.pause(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return downloader.to_payload(task)


@router.post("/download/{task_id}/resume")
def resume_download(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.resume(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return downloader.to_payload(task)


@router.post("/download/{task_id}/cancel")
def cancel_download(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.cancel(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return downloader.to_payload(task)


@router.post("/download/{task_id}/restart")
def restart_download(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.restart(task_id, user.id, db=db)
    if task is None:
        raise problem(404, "MODEL_DOWNLOAD_NOT_FOUND", "Download task was not found.", correlation=correlation_id())
    return downloader.to_payload(task)


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
            runtime=options.runtime,
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
