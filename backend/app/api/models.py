"""Model management API routes."""

from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from models.records import User
from pydantic import BaseModel
from services.downloader import downloader
from services.model_manager import ModelManager
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


def _manager(db: DBSession) -> ModelManager:
    return ModelManager(db)


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


@router.get("/{model_id}")
def get_model(
    model_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    model = _manager(db).info(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model.to_dict()


@router.delete("/{model_id}")
def remove_model(
    model_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ok = _manager(db).remove(model_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="模型不存在")
    return {"ok": True}