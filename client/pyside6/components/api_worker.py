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

    def __init__(self, operation: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            self.succeeded.emit(self._operation())
        except Exception as exc:  # Boundary: the UI renders the failure safely.
            self.failed.emit(str(exc))


class AsyncApiMixin:
    """Keeps background API workers alive until they have emitted a result."""

    def _init_async_api(self) -> None:
        self._api_workers: set[ApiWorker] = set()

    def _run_api(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[str], None],
    ) -> ApiWorker:
        worker = ApiWorker(operation, self)
        self._api_workers.add(worker)
        worker.succeeded.connect(on_success)
        worker.failed.connect(on_failure)
        worker.finished.connect(lambda: self._api_workers.discard(worker))
        worker.start()
        return worker
