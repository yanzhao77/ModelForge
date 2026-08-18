from __future__ import annotations

from typing import Any


class DBMemoryProvider:
    """MemoryProvider port backed by the 2.1 memory store (DB)."""

    async def retrieve(
        self,
        user_id: int,
        query: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
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
        self._store: dict[str, list[dict[str, Any]]] = {}

    def _key(self, agent_id: str, session_id: int | None) -> str:
        return "{}:{}".format(agent_id, session_id or "global")

    async def remember(
        self, agent_id: str, session_id: int | None, content: dict[str, Any],
    ) -> None:
        self._store.setdefault(self._key(agent_id, session_id), []).append(content)

    async def recall(
        self, agent_id: str, session_id: int | None, limit: int = 20,
    ) -> list[dict[str, Any]]:
        items = self._store.get(self._key(agent_id, session_id), [])
        return items[-limit:]

    async def clear(self, agent_id: str, session_id: int | None) -> None:
        self._store.pop(self._key(agent_id, session_id), None)