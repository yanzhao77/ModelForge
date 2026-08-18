"""Knowledge Base API routes."""
import os
import tempfile

from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from models.records import User
from pydantic import BaseModel
from services.runtime_registry import get_runtime
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class AnswerRequest(BaseModel):
    question: str
    top_k: int = 5
    model: str = "default-model"


_knowledge_base = None


def set_knowledge_base(kb):
    global _knowledge_base
    _knowledge_base = kb


def _get_kb():
    if _knowledge_base is None:
        raise HTTPException(status_code=503, detail="Knowledge base not initialized")
    return _knowledge_base


@router.post("/upload")
async def knowledge_upload(
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = _get_kb()
    suffix = os.path.splitext(file.filename or "upload.txt")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        result = kb.upload(tmp_path, db=db, user_id=user.id, filename=file.filename)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/documents")
def knowledge_documents(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return _get_kb().documents(db=db, user_id=user.id)


@router.get("/documents/{filename}/chunks")
def knowledge_chunks(
    filename: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _get_kb().chunks(filename, db=db, user_id=user.id)


@router.delete("/documents/{filename}")
def knowledge_delete_document(
    filename: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ok = _get_kb().delete_document(filename, db=db, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True}


@router.post("/query")
def knowledge_query(
    req: QueryRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _get_kb().query(req.question, top_k=req.top_k, db=db, user_id=user.id)


@router.post("/answer")
async def knowledge_answer(
    req: AnswerRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = _get_kb()
    return await kb.answer(
        req.question, top_k=req.top_k, db=db, user_id=user.id, runtime=get_runtime(), model=req.model
    )


@router.get("/stats")
def knowledge_stats(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return _get_kb().stats(db=db, user_id=user.id)