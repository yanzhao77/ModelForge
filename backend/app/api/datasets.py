"""Dataset API routes."""

from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from models.records import User
from services.dataset_service import DatasetService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/upload")
def upload_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    content = file.file.read()
    try:
        rec = DatasetService().upload(db, user.id, file.filename or "dataset", content, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if rec.status == "error":
        raise HTTPException(status_code=400, detail=f"数据集解析失败: {rec.error}")
    return rec.to_dict()


@router.get("")
def list_datasets(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return [d.to_dict() for d in DatasetService().list(db, user.id)]


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rec = DatasetService().get(db, dataset_id, user.id)
    if rec is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return rec.to_dict()


@router.post("/{dataset_id}/validate")
def validate_dataset(
    dataset_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return DatasetService().validate(db, dataset_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ok = DatasetService().delete(db, dataset_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return {"ok": True}