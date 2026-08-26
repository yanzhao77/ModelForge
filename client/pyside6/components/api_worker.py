"""Shared background API-task utility for the PySide6 client.

The worker executes blocking HTTP client calls outside the Qt GUI thread and
marshals success/failure notifications back through Qt signals.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class ApiWorker(QThread):
    """Run one blocking API callable outside the GUI event loop."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, operation: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        if self.isInterruptionRequested():
            self.cancelled.emit()
            return
        try:
            result = self._operation()
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.succeeded.emit(result)
        except Exception as exc:  # Boundary: the UI renders the failure safely.
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.failed.emit(str(exc))


class AsyncApiMixin:
    """Keeps background API workers alive until they have emitted a result."""

    def _init_async_api(self) -> None:
        self._api_workers: set[ApiWorker] = set()
        self._api_request_generation: dict[str, int] = {}

    def invalidate_api_requests(self, request_key: str | None = None) -> None:
        """Make late results from a page/request generation harmless to the UI."""
        if request_key is None:
            for key in list(self._api_request_generation):
                self._api_request_generation[key] += 1
            return
        self._api_request_generation[request_key] = self._api_request_generation.get(request_key, 0) + 1

    def _run_api(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[str], None],
        request_key: str | None = None,
    ) -> ApiWorker:
        generation = None
        if request_key is not None:
            generation = self._api_request_generation.get(request_key, 0) + 1
            self._api_request_generation[request_key] = generation
        worker = ApiWorker(operation, self)
        self._api_workers.add(worker)
        worker.succeeded.connect(lambda result: on_success(result) if request_key is None or self._api_request_generation.get(request_key) == generation else None)
        worker.failed.connect(lambda message: on_failure(message) if request_key is None or self._api_request_generation.get(request_key) == generation else None)
        worker.finished.connect(lambda: self._api_workers.discard(worker))
        worker.start()
        return worker

    def shutdown_async_api(self, wait_ms: int = 2500) -> None:
        """Stop or join owned one-shot workers before their Qt parent is destroyed."""
        workers = list(self._api_workers)
        self.invalidate_api_requests()
        for worker in workers:
            worker.requestInterruption()
        for worker in workers:
            if worker.isRunning() and not worker.wait(wait_ms):
                # A blocking socket cannot be safely force-killed. Detach its
                # UI callbacks; the client timeout and finished callback will
                # release it without delivering a stale page result.
                for signal in (worker.succeeded, worker.failed, worker.cancelled):
                    try:
                        signal.disconnect()
                    except (RuntimeError, TypeError):
                        pass
        self._api_workers = {worker for worker in self._api_workers if worker.isRunning()}
