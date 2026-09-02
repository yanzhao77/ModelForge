from __future__ import annotations

import builtins
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RunStore(Protocol):
    """Port: persistence for Run records (spec 30: Run -> DB)."""

    def create(self, run) -> Any: ...
    def get(self, run_id: str) -> Any | None: ...
    def list(self, user_id=None, agent_id=None, status=None, parent_run_id=None, limit=50, offset=0) -> builtins.list[Any]: ...
    def update(self, run_id: str, **fields) -> Any | None: ...


@runtime_checkable
class EventStore(Protocol):
    """Port: persistence for AgentEvents (spec 30)."""

    def append(self, event) -> None: ...
    def list(self, run_id: str, after_sequence: int = 0, limit: int = 1000) -> builtins.list[Any]: ...
    def last_sequence(self, run_id: str) -> int: ...
    def delete_older_than(self, days: int) -> int: ...


@runtime_checkable
class AgentStore(Protocol):
    """Port: agent definitions (spec 3)."""

    def get(self, name: str) -> Any | None: ...
    def list(self) -> builtins.list[Any]: ...
    def create(self, agent: Any) -> Any: ...
    def delete(self, name: str) -> bool: ...


@runtime_checkable
class MemoryProvider(Protocol):
    """Port: cross-session memory retrieval (spec 17)."""

    async def retrieve(self, user_id, query: str, top_k: int = 3) -> list[dict[str, Any]]: ...


@runtime_checkable
class KnowledgeProvider(Protocol):
    """Port: RAG retrieval (spec 18)."""

    async def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]: ...


@runtime_checkable
class HistoryProvider(Protocol):
    """Port: long-term conversation history (Session) (spec 5)."""

    async def load(self, session_id, user_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]: ...