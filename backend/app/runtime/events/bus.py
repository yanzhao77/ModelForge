from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .types import AgentEvent

Subscriber = Callable[[AgentEvent], Awaitable[None]]


class EventBus:
    """In-process pub/sub with per-run strict sequence (spec 6 / 7).

    Events are dispatched to subscribers AND queued for the persistence
    writer (store) so clients can reconnect and resume (spec 30 / 31).
    """

    def __init__(self, store: Any | None = None):
        self._store = store
        self._subscribers: list[Subscriber] = []
        self._sequences: dict[str, int] = {}
        self._queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None
        self._started = False
        self._write_failures = 0

    # ---- lifecycle ----
    def start(self) -> None:
        """Mark the bus started; the persistence writer task is created lazily
        on the first publish (so start() works outside a running loop)."""
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._writer_task is not None:
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._writer_task, timeout=2.0)
            except Exception:
                pass
            self._writer_task = None

    async def _writer(self) -> None:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            try:
                await self._store.append(event)
            except Exception as e:
                # audit P0-4: persistence failures must be visible, not silent
                self._write_failures += 1
                logging.getLogger("modelforge.runtime.events").warning(
                    "event persistence failed", extra={"event": event.event_type, "run_id": event.run_id, "error": str(e)},
                )

    # ---- publish / subscribe ----
    async def publish(
        self,
        run_id: str,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        session_id: int | None = None,
        correlation_id: str | None = None,
    ) -> AgentEvent:
        seq = self._sequences.get(run_id, 0) + 1
        self._sequences[run_id] = seq
        event = AgentEvent(
            id=uuid.uuid4().hex,
            run_id=run_id,
            event_type=event_type,
            sequence=seq,
            payload=payload or {},
            session_id=session_id,
            correlation_id=correlation_id,
        )
        if self._store is not None:
            if self._writer_task is None:
                self._writer_task = asyncio.get_running_loop().create_task(self._writer())
            self._queue.put_nowait(event)
        for sub in list(self._subscribers):
            try:
                await sub(event)
            except Exception:
                pass
        return event

    def subscribe(self, subscriber: Subscriber) -> None:
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    @property
    def store(self) -> Any:
        """Persistence adapter (None = in-memory only)."""
        return self._store

    @property
    def write_failures(self) -> int:
        """Count of persistence write failures (audit P0-4 observability)."""
        return self._write_failures

    def prune(self, run_id: str) -> None:
        """Drop per-run bookkeeping once the run is terminal (audit P0-3)."""
        self._sequences.pop(run_id, None)

    def sequence_of(self, run_id: str) -> int:
        return self._sequences.get(run_id, 0)

    async def flush(self) -> None:
        """Drain pending persistence writes (used by tests / shutdown)."""
        if self._store is None:
            return
        while not self._queue.empty():
            event = self._queue.get_nowait()
            try:
                await self._store.append(event)
            except Exception:
                self._write_failures += 1