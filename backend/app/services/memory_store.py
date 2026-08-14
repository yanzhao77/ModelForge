"""Cross-session memory store (DB-backed, ported from legacy memory service)."""
import re
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from models.records import Memory


class MemoryStore:
    """Database-backed memory extraction, search, and formatting."""

    MEMORY_TYPE_PREFERENCE = "preference"
    MEMORY_TYPE_FACT = "fact"
    MEMORY_TYPE_CONTEXT = "context"
    MEMORY_TYPE_SKILL = "skill"

    PREFERENCE_KEYWORDS = ["喜欢", "不喜欢", "偏好", "习惯", "倾向", "更喜欢", "讨厌"]
    FACT_KEYWORDS = ["我是", "我在", "我的", "我叫", "我住在", "我来自", "我的工作是"]

    @staticmethod
    def create_memory(
        db: DBSession,
        user_id: int,
        memory_type: str,
        key: str,
        value: str,
        source_session_id: Optional[int] = None,
        importance: float = 1.0,
    ) -> Memory:
        existing = (
            db.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.memory_type == memory_type,
                Memory.key == key,
            )
            .first()
        )
        if existing:
            existing.value = value
            existing.importance = max(existing.importance, importance)
            existing.last_accessed = datetime.now(timezone.utc)
            existing.access_count += 1
            db.commit()
            db.refresh(existing)
            return existing
        memory = Memory(
            user_id=user_id,
            memory_type=memory_type,
            key=key,
            value=value,
            source_session_id=source_session_id,
            importance=importance,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory

    @staticmethod
    def get_user_memories(
        db: DBSession, user_id: int, memory_type: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Memory]:
        query = db.query(Memory).filter(Memory.user_id == user_id)
        if memory_type:
            query = query.filter(Memory.memory_type == memory_type)
        query = query.order_by(Memory.importance.desc(), Memory.last_accessed.desc())
        if limit:
            query = query.limit(limit)
        return query.all()

    @staticmethod
    def search_memories(
        db: DBSession, user_id: int, keyword: str, limit: int = 5
    ) -> List[Memory]:
        memories = (
            db.query(Memory)
            .filter(
                Memory.user_id == user_id,
                or_(Memory.key.contains(keyword), Memory.value.contains(keyword))
            )
            .order_by(Memory.importance.desc())
            .limit(limit)
            .all()
        )
        for memory in memories:
            memory.last_accessed = datetime.now(timezone.utc)
            memory.access_count += 1
        db.commit()
        return memories

    @staticmethod
    def extract_memories_from_message(
        db: DBSession, user_id: int, message_content: str, session_id: Optional[int] = None
    ) -> List[Memory]:
        """Rule-based extraction of preference/fact memories from a message."""
        extracted: List[Memory] = []
        sentences = re.split(r"[。！？\n]", message_content or "")
        rules = [
            (MemoryStore.MEMORY_TYPE_PREFERENCE, MemoryStore.PREFERENCE_KEYWORDS, 0.8),
            (MemoryStore.MEMORY_TYPE_FACT, MemoryStore.FACT_KEYWORDS, 0.9),
        ]
        for memory_type, keywords, importance in rules:
            for keyword in keywords:
                if keyword in message_content:
                    for sentence in sentences:
                        if keyword in sentence and sentence.strip():
                            mem = MemoryStore.create_memory(
                                db=db,
                                user_id=user_id,
                                memory_type=memory_type,
                                key=keyword,
                                value=sentence.strip(),
                                source_session_id=session_id,
                                importance=importance,
                            )
                            extracted.append(mem)
        return extracted

    @staticmethod
    def get_relevant_memories_for_query(
        db: DBSession, user_id: int, query: str, limit: int = 3
    ) -> List[Memory]:
        keywords = re.findall(r"[\u4e00-\u9fa5a-zA-Z]+", query or "")
        all_memories: List[Memory] = []
        for keyword in keywords[:5]:
            all_memories.extend(MemoryStore.search_memories(db, user_id, keyword, limit=2))
        unique = {m.id: m for m in all_memories}.values()
        return sorted(unique, key=lambda x: x.importance, reverse=True)[:limit]

    @staticmethod
    def format_memories_for_context(memories: List[Memory]) -> str:
        if not memories:
            return ""
        parts = ["[用户记忆]"]
        parts.extend(f"- {memory.value}" for memory in memories)
        return "\n".join(parts)

    @staticmethod
    def delete_memory(
        db: DBSession, memory_id: int, user_id: Optional[int] = None
    ) -> bool:
        query = db.query(Memory).filter(Memory.id == memory_id)
        if user_id is not None:
            query = query.filter(Memory.user_id == user_id)
        memory = query.first()
        if not memory:
            return False
        db.delete(memory)
        db.commit()
        return True

    @staticmethod
    def update_memory_importance(
        db: DBSession, memory_id: int, importance: float
    ) -> bool:
        memory = db.query(Memory).filter(Memory.id == memory_id).first()
        if not memory:
            return False
        memory.importance = max(0.0, min(1.0, importance))
        db.commit()
        return True