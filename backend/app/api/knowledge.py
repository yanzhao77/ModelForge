"""Knowledge Base API routes."""
import os
import tempfile

from core.api_contracts import correlation_id, operation_result, problem
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
    knowledge_binding: dict | None = None


class AnswerRequest(BaseModel):
    question: str
    top_k: int = 5
    model: str = "default-model"
    knowledge_binding: dict | None = None


_knowledge_base = None


def set_knowledge_base(kb):
    global _knowledge_base
    _knowledge_base = kb


def _get_kb(*, correlation: str | None = None):
    if _knowledge_base is None:
        raise problem(
            503,
            "KNOWLEDGE_BASE_UNAVAILABLE",
            "Knowledge base is not available.",
            correlation=correlation,
        )
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
    corr = correlation_id()
    ok = _get_kb(correlation=corr).delete_document(filename, db=db, user_id=user.id)
    if not ok:
        raise problem(404, "KNOWLEDGE_DOCUMENT_NOT_FOUND", "Knowledge document was not found.", correlation=corr)
    return operation_result({"ok": True, "filename": filename}, corr)


@router.post("/query")
def knowledge_query(
    req: QueryRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return _get_kb().query(req.question, top_k=req.top_k, db=db, user_id=user.id, knowledge_binding=req.knowledge_binding)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/answer")
async def knowledge_answer(
    req: AnswerRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = _get_kb()
    try:
        return await kb.answer(
            req.question, top_k=req.top_k, db=db, user_id=user.id, runtime=get_runtime(), model=req.model,
            knowledge_binding=req.knowledge_binding,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/stats")
def knowledge_stats(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return _get_kb().stats(db=db, user_id=user.id)
