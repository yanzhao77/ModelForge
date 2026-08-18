"""Memory API routes."""

from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from models.records import User
from pydantic import BaseModel
from services.memory_store import MemoryStore
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/memories", tags=["memories"])


class MemoryCreate(BaseModel):
    memory_type: str = "context"
    key: str
    value: str
    importance: float = 1.0


class MemoryUpdate(BaseModel):
    importance: float | None = None
    value: str | None = None


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
    if req.importance is not None:
        MemoryStore.update_memory_importance(db, memory_id, req.importance)
    return {"ok": True}


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: int, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ok = MemoryStore.delete_memory(db, memory_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}