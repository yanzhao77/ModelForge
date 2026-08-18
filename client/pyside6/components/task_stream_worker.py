"""Reconnectable background consumer for the global task SSE stream."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal


def normalize_task_event(event: dict) -> dict | None:
    """Convert API-client SSE data into the stable TaskStore event contract."""
    payload = event.get("payload")
    event_id = event.get("event_id", event.get("id"))
    if not isinstance(payload, dict):
        return None
    try:
        cursor = int(event_id)
    except (TypeError, ValueError):
        return None
    if cursor <= 0:
        return None
    return {
        "event_id": cursor,
        "event_type": str(event.get("event_type", event.get("event", "task.updated"))),
        "payload": payload if isinstance(payload.get("task"), dict) else {"task": payload},
    }

class TaskStreamWorker(QThread):
    """Consume server events off the GUI thread and resume from the last cursor."""

    event_received = Signal(object)
    stream_state = Signal(bool, str)

    def __init__(self, api, after_id: int = 0, parent=None):
        super().__init__(parent)
        self.api = api
        self._cursor = max(0, after_id)

    def set_cursor(self, cursor: int) -> None:
        self._cursor = max(self._cursor, int(cursor or 0))

    def run(self) -> None:
        delay = 1.0
        while not self.isInterruptionRequested():
            try:
                for event in self.api.stream_tasks(self._cursor):
                    if self.isInterruptionRequested():
                        return
                    normalized = normalize_task_event(event)
                    if normalized is None:
                        continue
                    self._cursor = max(self._cursor, normalized["event_id"])
                    delay = 1.0
                    self.stream_state.emit(True, "")
                    self.event_received.emit(normalized)
                if self.isInterruptionRequested():
                    return
                raise RuntimeError("任务事件流意外结束")
            except Exception as exc:
                if self.isInterruptionRequested():
                    return
                self.stream_state.emit(False, str(exc))
                time.sleep(delay)
                delay = min(15.0, delay * 2)
