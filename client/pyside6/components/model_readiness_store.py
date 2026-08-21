"""Shared asynchronous model-readiness snapshot store for desktop workspaces."""

from __future__ import annotations

import time

from components.api_worker import ApiWorker
from PySide6.QtCore import QObject, Signal


class ModelReadinessStore(QObject):
    """Fetch one credential-safe snapshot at a time and broadcast fresh state."""

    changed = Signal(object)
    failed = Signal(str)
    refreshing_changed = Signal(bool)

    def __init__(self, api, parent=None, max_age_seconds: float = 30.0):
        super().__init__(parent)
        self.api = api
        self.max_age_seconds = max_age_seconds
        self.snapshot: dict | None = None
        self._fetched_at = 0.0
        self._worker: ApiWorker | None = None
        self._request_id = 0

    def is_fresh(self) -> bool:
        return self.snapshot is not None and time.monotonic() - self._fetched_at < self.max_age_seconds

    def refresh(self, force: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not force and self.is_fresh():
            self.changed.emit(self.snapshot)
            return
        self._request_id += 1
        request_id = self._request_id
        worker = ApiWorker(self.api.model_readiness, self)
        self._worker = worker
        self.refreshing_changed.emit(True)
        worker.succeeded.connect(lambda result: self._succeeded(request_id, result))
        worker.failed.connect(lambda error: self._failed(request_id, error))
        worker.finished.connect(self._finished)
        worker.start()

    def invalidate(self) -> None:
        self._fetched_at = 0.0

    def _succeeded(self, request_id: int, snapshot: dict) -> None:
        if request_id != self._request_id:
            return
        self.snapshot = snapshot
        self._fetched_at = time.monotonic()
        self.changed.emit(snapshot)

    def _failed(self, request_id: int, error: str) -> None:
        if request_id == self._request_id:
            self.failed.emit(error)

    def _finished(self) -> None:
        self._worker = None
        self.refreshing_changed.emit(False)

    def shutdown(self, wait_ms: int = 2500) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(wait_ms)
        self._worker = None
