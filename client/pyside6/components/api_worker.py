"""Shared background API-task utility for the PySide6 client.

The worker executes blocking HTTP client calls outside the Qt GUI thread and
marshals success/failure notifications back through Qt signals.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


def safe_api_error_text(exc: Exception) -> str:
    """Return only the stable desktop error code and optional request identifier."""
    code = getattr(exc, "code", None)
    correlation = getattr(exc, "correlation_id", None)
    if isinstance(code, str) and code:
        suffix = f" (request_id: {correlation})" if isinstance(correlation, str) and correlation else ""
        return f"{code}{suffix}"
    return "CLIENT_REQUEST_FAILED"


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
            self.failed.emit(safe_api_error_text(exc))


# Workers whose page is already gone but whose blocking socket call is still
# running. They are kept alive on purpose: Qt aborts the process (qFatal) when
# a QThread is destroyed while running, which made "close the window during a
# slow request" exit with 0xC0000409 instead of closing.
_ORPHANED_WORKERS: set[ApiWorker] = set()


def _release_orphan(worker: ApiWorker) -> None:
    _ORPHANED_WORKERS.discard(worker)
    worker.deleteLater()


def retain_api_worker(worker: ApiWorker) -> None:
    """Detach a running worker from its page and hold it until it finishes."""
    worker.setParent(None)
    if worker in _ORPHANED_WORKERS:
        return
    _ORPHANED_WORKERS.add(worker)
    worker.finished.connect(lambda: _release_orphan(worker))


def pending_api_workers() -> int:
    """Number of detached workers that have not finished yet."""
    return len(_ORPHANED_WORKERS)


def wait_for_api_workers(timeout_ms: int = 5000) -> bool:
    """Join detached workers; ``False`` when one still runs at the deadline."""
    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    for worker in list(_ORPHANED_WORKERS):
        if not worker.isRunning():
            continue
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms > 0:
            worker.wait(remaining_ms)
    return not any(worker.isRunning() for worker in list(_ORPHANED_WORKERS))


class AsyncApiMixin:
    """Keeps background API workers alive until they have emitted a result."""

    def _init_async_api(self) -> None:
        self._api_workers: set[ApiWorker] = set()
        self._api_request_generation: dict[str, int] = {}
        # Shared with the connected callbacks: once the page is shutting down
        # a late result must be dropped without touching destroyed widgets.
        self._api_state: dict[str, Any] = {
            "suppressed": False,
            "generation": self._api_request_generation,
        }

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
        state = self._api_state
        workers = self._api_workers
        generation: int | None = None
        if request_key is not None:
            generation = state["generation"].get(request_key, 0) + 1
            state["generation"][request_key] = generation

        def deliver(callback: Callable[[Any], None], payload: Any) -> None:
            if state["suppressed"]:
                return
            if request_key is not None and state["generation"].get(request_key) != generation:
                return
            callback(payload)

        worker = ApiWorker(operation, self)
        workers.add(worker)
        worker.succeeded.connect(lambda result: deliver(on_success, result))
        worker.failed.connect(lambda message: deliver(on_failure, message))
        worker.finished.connect(lambda: workers.discard(worker))
        worker.start()
        return worker

    def shutdown_async_api(self, wait_ms: int = 2500) -> None:
        """Stop or detach owned one-shot workers before their Qt parent dies.

        Workers that cannot finish inside ``wait_ms`` are detached and kept
        alive until their socket call returns; destroying a running QThread
        aborts the whole process.
        """
        self._api_state["suppressed"] = True
        self.invalidate_api_requests()
        workers = list(self._api_workers)
        self._api_workers = set()
        for worker in workers:
            worker.requestInterruption()
        deadline = time.monotonic() + max(0, wait_ms) / 1000
        for worker in workers:
            # A worker that was started but has not entered run() yet is not
            # "running" for Qt but is still unsafe to destroy.
            if worker.isFinished():
                continue
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms > 0:
                worker.wait(remaining_ms)
        for worker in workers:
            if not worker.isFinished():
                # A blocking socket cannot be safely force-killed, so hand it
                # to the process-wide holder instead of letting its page
                # destroy it.
                retain_api_worker(worker)
