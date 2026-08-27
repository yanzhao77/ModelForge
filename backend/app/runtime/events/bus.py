from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from services.redaction import is_sensitive_key, redact_data

from .types import AgentEvent

Subscriber = Callable[[AgentEvent], Awaitable[None]]

_EVENT_BODY_KEYS = frozenset({
    "arguments", "content", "context", "input", "message", "messages",
    "output", "prompt", "question", "answer", "knowledge", "document",
    "error", "detail", "result",
})


def _safe_event_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded, credential- and body-safe event payload.

    Events can be persisted and streamed, so they are not a suitable channel for
    model input/output, knowledge text, or tool arguments. Preserve stable
    non-content facts and mark any removed body so consumers do not mistake the
    redacted payload for an execution result.
    """
    redacted = False
    safe: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        normalized = str(key).lower().replace("-", "_")
        if normalized in _EVENT_BODY_KEYS or is_sensitive_key(key):
            safe[str(key)] = "[REDACTED]"
            redacted = True
            continue
        safe[str(key)] = redact_data(value, max_depth=8, max_text_length=1_024)
    if redacted:
        safe["payload_redacted"] = True
    return safe


class EventBus:
    """In-process pub/sub with per-run strict sequence (spec 6 / 7).

    Events are dispatched to subscribers AND queued for the persistence
    writer (store) so clients can reconnect and resume (spec 30 / 31).
    """

    def __init__(self, store: Any | None = None, queue_maxsize: int = 512):
        self._store = store
        self._subscribers: list[Subscriber] = []
        self._sequences: dict[str, int] = {}
        self._queue = asyncio.Queue(maxsize=max(1, queue_maxsize))
        self._writer_task: asyncio.Task | None = None
        self._started = False
        self._write_failures = 0
        self._queue_overflows = 0

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
            try:
                if event is None:
                    return
                result = self._store.append(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                # audit P0-4: persistence failures must be visible, not silent
                self._write_failures += 1
                logging.getLogger("modelforge.runtime.events").warning(
                    "event persistence failed", extra={"event": event.event_type, "run_id": event.run_id, "error_type": type(e).__name__},
                )
            finally:
                self._queue.task_done()

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
        if run_id not in self._sequences and self._store is not None:
            try:
                self._sequences[run_id] = max(0, int(self._store.last_sequence(run_id)))
            except Exception:
                # Store availability must not block live events; the writer
                # failure counter still exposes any later persistence problem.
                self._sequences[run_id] = 0
        seq = self._sequences.get(run_id, 0) + 1
        self._sequences[run_id] = seq
        event = AgentEvent(
            id=uuid.uuid4().hex,
            run_id=run_id,
            event_type=event_type,
            sequence=seq,
            payload=_safe_event_payload(payload),
            session_id=session_id,
            correlation_id=correlation_id,
            event_key=f"{event_type}:{seq}",
        )
        if self._store is not None:
            if self._writer_task is None:
                self._writer_task = asyncio.get_running_loop().create_task(self._writer())
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                # Do not silently discard a durable run fact. The bounded queue
                # protects memory; overflow falls back to one direct append and
                # remains observable for operational review.
                self._queue_overflows += 1
                result = self._store.append(event)
                if inspect.isawaitable(result):
                    await result
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

    @property
    def queue_overflows(self) -> int:
        """Count synchronous overflow fallbacks; non-zero needs operator review."""
        return self._queue_overflows

    def diagnostics_snapshot(self) -> dict[str, int | bool]:
        """Return aggregate queue health without reading or changing events."""
        writer = self._writer_task
        return {
            "started": self._started,
            "store_configured": self._store is not None,
            "queue_depth": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "subscriber_count": len(self._subscribers),
            "writer_active": writer is not None and not writer.done(),
            "write_failure_count": self._write_failures,
            "queue_overflow_count": self._queue_overflows,
            "tracked_sequence_count": len(self._sequences),
        }

    def prune(self, run_id: str) -> None:
        """Drop per-run bookkeeping once the run is terminal (audit P0-3)."""
        self._sequences.pop(run_id, None)

    def sequence_of(self, run_id: str) -> int:
        return self._sequences.get(run_id, 0)

    async def flush(self) -> None:
        """Wait until both queued and in-flight persistence writes are complete."""
        if self._store is None:
            return
        if self._writer_task is not None:
            await self._queue.join()
