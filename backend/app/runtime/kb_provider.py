"""KnowledgeProvider + HistoryProvider adapters for the Context Engine."""
from __future__ import annotations

from typing import Any


class KBKnowledgeProvider:
    """KnowledgeProvider port backed by the RAG knowledge base (spec 18)."""

    def __init__(self, kb: Any = None):
        self._kb = kb

    async def retrieve(self, query: str, top_k: int = 3, user_id: int | None = None, knowledge_binding: dict | None = None) -> list[dict[str, Any]]:
        kb = self._kb
        if kb is None:
            from services.knowledge_base import get_global_kb
            kb = get_global_kb()
        if user_id is None:
            return []
        from core.database import SessionLocal
        with SessionLocal() as db:
            result = kb.query(query, top_k=top_k, db=db, user_id=user_id, knowledge_binding=knowledge_binding)
        return [
            {
                "text": r.get("text", ""),
                "source": r.get("source", "?"),
                "document_id": r.get("document_id"),
                "chunk_id": r.get("chunk_id"),
                "collections": r.get("collections", []),
            }
            for r in (result.get("results") or [])
        ]


class SessionHistoryProvider:
    """HistoryProvider port backed by the sessions table (spec 5)."""

    async def load(self, session_id: int, limit: int = 20) -> list[dict[str, Any]]:
        from core.database import SessionLocal
        from services.session_service import SessionService
        with SessionLocal() as db:
            msgs = SessionService.get_session_messages(db, session_id, limit=limit, offset=0)
            return [
                {"role": m.role, "content": m.content}
                for m in msgs if m.role in ("user", "assistant")
            ]
