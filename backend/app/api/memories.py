"""Memory API routes."""

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends
from models.records import Memory, User
from pydantic import BaseModel, Field
from services.audit_log import (
    AuditMetadataRejected,
    AuditPersistenceError,
    commit_control_plane_audit,
    record_control_plane_operation,
    validate_control_plane_audit_metadata,
)
from services.memory_store import MemoryStore
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/memories", tags=["memories"])


class MemoryCreate(BaseModel):
    memory_type: str = "context"
    key: str
    value: str
    importance: float = 1.0


class MemoryUpdate(BaseModel):
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    value: str | None = Field(default=None, min_length=1, max_length=200000)
    request_id: str | None = Field(default=None, max_length=64)


class MemoryActionRequest(BaseModel):
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


def _memory_unavailable(correlation: str):
    raise problem(404, "MEMORY_UNAVAILABLE", "Memory is unavailable.", correlation=correlation)


def _memory_audit_or_problem(
    db: DBSession,
    *,
    user_id: int,
    action: str,
    memory_id: int,
    correlation: str,
    metadata: dict,
) -> None:
    try:
        validate_control_plane_audit_metadata(action, metadata)
        record_control_plane_operation(db, user_id=user_id, action=action, object_type="memory", object_id=str(memory_id), correlation_id=correlation, metadata=metadata)
        commit_control_plane_audit(db)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    except AuditPersistenceError as exc:
        raise problem(503, "MEMORY_AUDIT_DURABILITY_UNKNOWN", "Memory action was accepted, but audit durability is unknown.", correlation=correlation) from exc


@router.get("")
def list_memories(
    memory_type: str | None = None, limit: int | None = None,
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    memories = MemoryStore.get_user_memories(db, user.id, memory_type, limit)
    return [mm.to_dict() for mm in memories]


@router.post("")
def create_memory(
    req: MemoryCreate, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    memory = MemoryStore.create_memory(
        db, user.id, req.memory_type, req.key, req.value, importance=req.importance
    )
    return memory.to_dict()


@router.get("/search")
def search_memories(
    q: str, limit: int = 5, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    memories = MemoryStore.search_memories(db, user.id, q, limit)
    return [mm.to_dict() for mm in memories]


@router.patch("/{memory_id}")
def update_memory(
    memory_id: int, req: MemoryUpdate, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    correlation = req.request_id or correlation_id()
    metadata = {
        "request_id_supplied": bool(req.request_id),
        "value_changed": req.value is not None,
        "importance_changed": req.importance is not None,
    }
    try:
        validate_control_plane_audit_metadata("memory.update", metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    memory = db.query(Memory).filter(Memory.id == memory_id, Memory.user_id == user.id).first()
    if memory is None:
        _memory_unavailable(correlation)
    if req.value is not None:
        memory.value = req.value
    if req.importance is not None:
        memory.importance = max(0.0, min(1.0, req.importance))
    _memory_audit_or_problem(db, user_id=user.id, action="memory.update", memory_id=memory_id, correlation=correlation, metadata=metadata)
    db.refresh(memory)
    return operation_result(memory.to_dict(), correlation)


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: int, req: MemoryActionRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    correlation = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "MEMORY_DELETE_CONFIRMATION_REQUIRED", "Confirm before deleting a memory.", correlation=correlation)
    metadata = {"confirmed": True}
    try:
        validate_control_plane_audit_metadata("memory.delete", metadata)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    memory = db.query(Memory).filter(Memory.id == memory_id, Memory.user_id == user.id).first()
    if memory is None:
        _memory_unavailable(correlation)
    db.delete(memory)
    _memory_audit_or_problem(db, user_id=user.id, action="memory.delete", memory_id=memory_id, correlation=correlation, metadata=metadata)
    return operation_result({"ok": True}, correlation)
