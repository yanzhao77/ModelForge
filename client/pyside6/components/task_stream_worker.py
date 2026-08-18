"""Reconnectable background consumer for the global task SSE stream."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal


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
                self.stream_state.emit(True, "")
                for event in self.api.stream_tasks(self._cursor):
                    if self.isInterruptionRequested():
                        return
                    payload = event.get("payload") or {}
                    event_id = payload.get("event_id") or event.get("id")
                    try:
                        self._cursor = max(self._cursor, int(event_id))
                    except (TypeError, ValueError):
                        pass
                    self.event_received.emit(payload)
                if self.isInterruptionRequested():
                    return
                raise RuntimeError("任务事件流意外结束")
            except Exception as exc:
                if self.isInterruptionRequested():
                    return
                self.stream_state.emit(False, str(exc))
                time.sleep(delay)
                delay = min(15.0, delay * 2)
            else:
                delay = 1.0
