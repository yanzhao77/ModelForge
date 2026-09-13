"""Knowledge Base API routes."""
import asyncio
import os
import tempfile

from core.api_contracts import correlation_id, operation_result, problem
from core.config import settings
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, File, Form, UploadFile
from models.records import User
from pydantic import BaseModel
from services.inference_errors import classify_inference_exception
from services.resource_lease import ResourceBusy, inference_lease, transient_hold
from services.runtime_registry import get_runtime
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    knowledge_binding: dict | None = None
    #: V1.4 retrieval strategy: semantic | keyword | hybrid | rerank
    retrieval_mode: str | None = None


class AnswerRequest(BaseModel):
    question: str
    top_k: int = 5
    model: str = "default-model"
    knowledge_binding: dict | None = None
    retrieval_mode: str | None = None


class KnowledgeBaseRequest(BaseModel):
    name: str
    description: str | None = None
    tags: list[str] | None = None


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class KnowledgeDocumentBindingRequest(BaseModel):
    document_id: int


class EmbedRequest(BaseModel):
    texts: list[str]
    model_id: int | None = None


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
    knowledge_id: str | None = Form(default=None),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    kb = _get_kb(correlation=corr)
    suffix = os.path.splitext(file.filename or "upload.txt")[1]
    total = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        while chunk := await file.read(64 * 1024):
            total += len(chunk)
            if total > settings.max_upload_size:
                tmp.close()
                os.unlink(tmp_path)
                raise problem(413, "KNOWLEDGE_FILE_TOO_LARGE", "Knowledge file exceeds the configured size limit.", correlation=corr)
            tmp.write(chunk)
    try:
        # Parsing, chunking, embedding and the DB write are synchronous and can
        # take seconds on a large document. Running them on the event loop froze
        # every other request in the process for the whole upload.
        result = await asyncio.to_thread(
            kb.upload, tmp_path, db=db, user_id=user.id, filename=file.filename
        )
        document_id = await asyncio.to_thread(
            _attach_and_project, db, user.id, file.filename, knowledge_id, result
        )
        return {**result, "document_id": document_id, "knowledge_id": knowledge_id}
    except ValueError as exc:
        raise problem(400, "KNOWLEDGE_UPLOAD_INVALID", "Knowledge upload was rejected.", correlation=corr) from exc
    except RuntimeError as exc:
        raise problem(501, "KNOWLEDGE_FEATURE_UNAVAILABLE", "Knowledge upload is not available in this deployment.", correlation=corr) from exc
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _attach_and_project(db, user_id: int, filename: str | None, knowledge_id: str | None, result: dict) -> int | None:
    """Attach an ingested document to a base and publish index progress.

    Both steps are best-effort: a library/task-center hiccup must not turn a
    successful ingestion into an error, because the document is already indexed.
    """
    from models.records import KnowledgeDocument

    document_id: int | None = None
    if filename and result.get("status") == "ingested":
        try:
            service = _knowledge_service(db)
            if knowledge_id:
                service.attach_latest(user_id, knowledge_id, filename)
            document = (
                db.query(KnowledgeDocument)
                .filter_by(user_id=user_id, filename=filename)
                .order_by(KnowledgeDocument.created_at.desc())
                .first()
            )
            document_id = document.id if document is not None else None
        except Exception:
            document_id = None
    _project_index_task(db, user_id, filename, result)
    return document_id


def _project_index_task(db, user_id: int, filename: str | None, result: dict) -> None:
    """Surface ingestion in the unified task center (V1.4/§18)."""
    try:
        from services.task_realtime import task_outbox_publisher
        from services.task_service import TaskService

        TaskService().project(
            db,
            user_id=user_id,
            task_type="knowledge_index",
            source="knowledge",
            source_task_id=str(filename or "upload"),
            title=f"知识库索引：{filename or 'upload'}",
            status="SUCCEEDED" if result.get("status") == "ingested" else "FAILED",
            summary=f"{result.get('chunks', 0)} 个分块",
            progress_percent=100 if result.get("status") == "ingested" else 0,
            cancelable=False,
            retryable=result.get("status") != "ingested",
            metadata={
                "filename": filename,
                "chunks": result.get("chunks", 0),
                "type": result.get("type"),
            },
        )
        task_outbox_publisher.nudge()
    except Exception:
        return


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
        return _get_kb().query(
            req.question,
            top_k=req.top_k,
            db=db,
            user_id=user.id,
            knowledge_binding=req.knowledge_binding,
            retrieval_mode=req.retrieval_mode,
        )
    except ValueError as exc:
        raise problem(422, "KNOWLEDGE_QUERY_REJECTED", "Knowledge query was rejected.", correlation=correlation_id()) from exc


@router.post("/answer")
async def knowledge_answer(
    req: AnswerRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = _get_kb()
    try:
        # A RAG answer runs inference, so it shares the exclusive runtime lease.
        with transient_hold(inference_lease, user_id=user.id, username=user.username):
            return await kb.answer(
                req.question, top_k=req.top_k, db=db, user_id=user.id, runtime=get_runtime(), model=req.model,
                knowledge_binding=req.knowledge_binding, retrieval_mode=req.retrieval_mode,
            )
    except ResourceBusy as exc:
        raise exc.to_problem() from exc
    except ValueError as exc:
        raise problem(422, "KNOWLEDGE_ANSWER_REJECTED", "Knowledge answer was rejected.", correlation=correlation_id()) from exc
    except Exception as exc:
        # A RAG answer runs inference, so an unreachable or failing provider
        # must produce the same stable code as /chat instead of a bare 500.
        classification = classify_inference_exception(exc)
        raise classification.to_problem(correlation_id()) from exc


@router.get("/stats")
def knowledge_stats(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return _get_kb().stats(db=db, user_id=user.id)


# ---------------- V1.4 knowledge bases / collections ----------------


def _knowledge_service(db: DBSession):
    from services.knowledge_service import KnowledgeService

    return KnowledgeService(db, kb=_knowledge_base)


def _kb_problem(exc, corr: str):
    return problem(exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None)


@router.get("/bases")
def list_knowledge_bases(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return {"knowledge_bases": _knowledge_service(db).list_bases(user.id)}


@router.post("/bases")
def create_knowledge_base(
    req: KnowledgeBaseRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services.knowledge_service import KnowledgeServiceError

    corr = correlation_id()
    try:
        base = _knowledge_service(db).create_base(user.id, req.name, req.description, req.tags)
    except KnowledgeServiceError as exc:
        raise _kb_problem(exc, corr) from exc
    return operation_result(base, corr)


@router.get("/bases/{base_id}")
def get_knowledge_base(
    base_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from services.knowledge_service import KnowledgeServiceError

    try:
        return _knowledge_service(db).get_base(user.id, base_id)
    except KnowledgeServiceError as exc:
        raise _kb_problem(exc, correlation_id()) from exc


@router.patch("/bases/{base_id}")
def update_knowledge_base(
    base_id: str,
    req: KnowledgeBaseUpdateRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services.knowledge_service import KnowledgeServiceError

    corr = correlation_id()
    try:
        base = _knowledge_service(db).update_base(
            user.id, base_id, name=req.name, description=req.description, tags=req.tags
        )
    except KnowledgeServiceError as exc:
        raise _kb_problem(exc, corr) from exc
    return operation_result(base, corr)


@router.delete("/bases/{base_id}")
def delete_knowledge_base(
    base_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from services.knowledge_service import KnowledgeServiceError

    corr = correlation_id()
    try:
        _knowledge_service(db).delete_base(user.id, base_id)
    except KnowledgeServiceError as exc:
        raise _kb_problem(exc, corr) from exc
    return operation_result({"ok": True, "knowledge_id": base_id}, corr)


@router.get("/bases/{base_id}/documents")
def list_knowledge_base_documents(
    base_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from services.knowledge_service import KnowledgeServiceError

    try:
        return {"documents": _knowledge_service(db).documents(user.id, base_id)}
    except KnowledgeServiceError as exc:
        raise _kb_problem(exc, correlation_id()) from exc


@router.post("/bases/{base_id}/documents")
def attach_knowledge_document(
    base_id: str,
    req: KnowledgeDocumentBindingRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services.knowledge_service import KnowledgeServiceError

    corr = correlation_id()
    try:
        result = _knowledge_service(db).attach_document(user.id, base_id, req.document_id)
    except KnowledgeServiceError as exc:
        raise _kb_problem(exc, corr) from exc
    return operation_result(result, corr)


@router.delete("/bases/{base_id}/documents/{document_id}")
def detach_knowledge_document(
    base_id: str,
    document_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from services.knowledge_service import KnowledgeServiceError

    corr = correlation_id()
    try:
        removed = _knowledge_service(db).detach_document(user.id, base_id, document_id)
    except KnowledgeServiceError as exc:
        raise _kb_problem(exc, corr) from exc
    if not removed:
        raise problem(404, "KNOWLEDGE_BINDING_NOT_FOUND", "Document is not in this knowledge base.", correlation=corr)
    return operation_result({"ok": True}, corr)


@router.get("/embedding")
def embedding_status(
    model_id: int | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Which embedding provider would be used, and why (V1.4)."""
    return _knowledge_service(db).embedding_status(user.id, model_id=model_id)


@router.post("/embed")
def embed_texts_endpoint(
    req: EmbedRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Embed text with the selected provider (registry model or hash fallback)."""
    from services.embedding_service import embed_texts

    corr = correlation_id()
    if not req.texts:
        raise problem(422, "KNOWLEDGE_EMBED_REJECTED", "At least one text is required.", correlation=corr)
    if len(req.texts) > 64:
        raise problem(422, "KNOWLEDGE_EMBED_REJECTED", "At most 64 texts may be embedded per request.", correlation=corr)
    try:
        return embed_texts(db, user.id, req.texts, model_id=req.model_id)
    except ValueError as exc:
        raise problem(422, "KNOWLEDGE_EMBED_REJECTED", "Embedding request was rejected.", correlation=corr) from exc
