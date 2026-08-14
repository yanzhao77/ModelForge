from __future__ import annotations

from typing import Any, Dict, List, Optional


class DBMemoryProvider:
    """MemoryProvider port backed by the 2.1 memory store (DB)."""

    async def retrieve(
        self,
        user_id: int,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        from core.database import SessionLocal
        from services.memory_store import MemoryStore
        with SessionLocal() as db:
            memories = MemoryStore.get_relevant_memories_for_query(
                db, user_id, query, limit=top_k,
            )
            return [
                {
                    "type": m.memory_type,
                    "key": m.key,
                    "value": m.value,
                    "importance": m.importance,
                }
                for m in memories
            ]


class ConversationMemory:
    """Working / conversation memory in-process (spec 17).

    Keyed by agent+session; survives within the process lifetime.
    """

    def __init__(self):
        self._store: Dict[str, List[Dict[str, Any]]] = {}

    def _key(self, agent_id: str, session_id: Optional[int]) -> str:
        return "{}:{}".format(agent_id, session_id or "global")

    async def remember(
        self, agent_id: str, session_id: Optional[int], content: Dict[str, Any],
    ) -> None:
        self._store.setdefault(self._key(agent_id, session_id), []).append(content)

    async def recall(
        self, agent_id: str, session_id: Optional[int], limit: int = 20,
    ) -> List[Dict[str, Any]]:
        items = self._store.get(self._key(agent_id, session_id), [])
        return items[-limit:]

    async def clear(self, agent_id: str, session_id: Optional[int]) -> None:
        self._store.pop(self._key(agent_id, session_id), None)