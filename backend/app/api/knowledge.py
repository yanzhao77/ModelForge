"""Knowledge Base API routes."""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
import tempfile
import os

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


_knowledge_base = None


def set_knowledge_base(kb):
    global _knowledge_base
    _knowledge_base = kb


@router.post("/upload")
async def knowledge_upload(file: UploadFile = File(...)):
    """Upload and ingest a document."""
    if _knowledge_base is None:
        raise HTTPException(status_code=503, detail="Knowledge base not initialized")

    # Save uploaded file to temp location
    suffix = os.path.splitext(file.filename or "upload.txt")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = _knowledge_base.upload(tmp_path)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/query")
async def knowledge_query(req: QueryRequest):
    """Query the knowledge base."""
    if _knowledge_base is None:
        raise HTTPException(status_code=503, detail="Knowledge base not initialized")
    return _knowledge_base.query(req.question, top_k=req.top_k)


@router.get("/stats")
async def knowledge_stats():
    """Get knowledge base statistics."""
    if _knowledge_base is None:
        raise HTTPException(status_code=503, detail="Knowledge base not initialized")
    return _knowledge_base.stats()
