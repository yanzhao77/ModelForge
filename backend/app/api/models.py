"""Model management API routes."""

from typing import Literal

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from models.records import User
from pydantic import BaseModel, Field
from services.downloader import downloader
from services.audit_log import record_operation
from services.model_manager import ModelManager
from services.model_readiness_service import ModelReadinessError, ModelReadinessService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/models", tags=["models"])


class ScanRequest(BaseModel):
    path: str | None = None


class InstallRequest(BaseModel):
    name: str
    provider: str = "local"
    path: str
    size: str = ""
    format: str | None = None
    quant: str | None = None


class DownloadRequest(BaseModel):
    repo_id: str
    filename: str | None = None


class DefaultModelRequest(BaseModel):
    kind: Literal["local", "remote"]
    model_ref: str = Field(min_length=1, max_length=255)
    provider_id: int | None = None
    request_id: str | None = Field(default=None, max_length=64)


def _manager(db: DBSession) -> ModelManager:
    return ModelManager(db)


def _readiness(db: DBSession) -> ModelReadinessService:
    return ModelReadinessService(db)


@router.get("")
def list_models(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    models = _manager(db).list(user.id)
    return [m.to_dict() for m in models]


@router.post("/scan")
def scan_models(
    req: ScanRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    models = _manager(db).scan(req.path, user.id)
    return [m.to_dict() for m in models]


@router.post("/install")
def install_model(
    req: InstallRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    model = _manager(db).install(
        req.name, req.provider, req.path, req.size, user.id, req.format, req.quant
    )
    return model.to_dict()


@router.get("/search")
def search_hf_models(
    q: str = "", author: str | None = None, limit: int = 20,
    user: User = Depends(get_current_user),
):
    try:
        return downloader.search_hf(q, author, limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"搜索失败: {e}")


@router.post("/download")
def download_model(
    req: DownloadRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.start(req.repo_id, req.filename)
    return task.to_dict()


@router.get("/download/{task_id}")
def download_status(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = downloader.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
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


@router.get("/{model_id}")
def get_model(
    model_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    model = _manager(db).info(model_id)
    if model is None:
        raise problem(404, "LOCAL_MODEL_NOT_FOUND", "Local model record was not found.")
    return model.to_dict()


@router.delete("/{model_id}")
def remove_model(
    model_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ok = _manager(db).remove(model_id, user.id)
    if not ok:
        raise problem(404, "LOCAL_MODEL_NOT_FOUND", "Local model record was not found.")
    return {"ok": True}
