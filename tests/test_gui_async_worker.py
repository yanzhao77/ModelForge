"""Regression tests for non-blocking PySide6 API task execution."""
import pytest

pytestmark = pytest.mark.desktop

import logging
import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client" / "pyside6"))

from components.api_worker import (  # noqa: E402
    ApiWorker,
    AsyncApiMixin,
    log_pending_api_workers,
    orphaned_worker_report,
    pending_api_workers,
    wait_for_api_workers,
)
from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _app():
    # A QCoreApplication here would make every later GUI module that needs a
    # QApplication fail, so the suite stays order-independent by using one.
    return QApplication.instance() or QApplication([])


def test_api_worker_executes_blocking_operation_off_gui_thread():
    app = _app()
    main_thread = threading.get_ident()
    operation_thread = []
    received = []

    def operation():
        operation_thread.append(threading.get_ident())
        time.sleep(0.02)
        return {"ok": True}

    worker = ApiWorker(operation)
    worker.succeeded.connect(received.append)
    worker.start()

    deadline = time.monotonic() + 2.0
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    worker.wait(1000)

    assert received == [{"ok": True}]
    assert operation_thread and operation_thread[0] != main_thread


class _Host(QObject, AsyncApiMixin):
    """Minimal page-like owner of background workers."""

    def __init__(self):
        super().__init__()
        self._init_async_api()
        self.results = []


def test_shutdown_detaches_a_running_worker_instead_of_destroying_it():
    app = _app()
    host = _Host()
    release = threading.Event()
    started = threading.Event()

    def slow_operation():
        started.set()
        release.wait(10)
        return []

    host._run_api(
        slow_operation,
        host.results.append,
        host.results.append,
        request_key="slow.refresh",
    )
    assert started.wait(5), "the worker never entered the request"
    assert host._api_workers

    # Qt aborts the process when a running QThread is destroyed with its page,
    # so the worker has to be detached and kept alive instead.
    host.shutdown_async_api(wait_ms=50)
    assert host._api_workers == set()
    assert pending_api_workers() >= 1

    release.set()
    assert wait_for_api_workers(5000) is True
    # The page is shutting down: a late answer must never reach its widgets.
    app.processEvents()
    assert host.results == []


def test_retained_workers_are_reported_with_age_and_operation():
    app = _app()
    host = _Host()
    release = threading.Event()
    started = threading.Event()

    def slow_operation():
        started.set()
        release.wait(10)
        return []

    host._run_api(
        slow_operation,
        host.results.append,
        host.results.append,
        request_key="slow.refresh",
    )
    assert started.wait(5)
    host.shutdown_async_api(wait_ms=50)

    report = orphaned_worker_report()
    assert len(report) == 1
    assert report[0]["running"] is True
    assert report[0]["operation"].endswith("slow_operation")
    assert isinstance(report[0]["retained_ms"], int)

    release.set()
    assert wait_for_api_workers(5000) is True
    app.processEvents()
    assert orphaned_worker_report() == []


def test_pending_workers_are_logged_before_the_process_exits(caplog):
    _app()
    host = _Host()
    release = threading.Event()
    started = threading.Event()

    def slow_operation():
        started.set()
        release.wait(10)
        return []

    host._run_api(slow_operation, host.results.append, host.results.append)
    assert started.wait(5)
    host.shutdown_async_api(wait_ms=50)

    with caplog.at_level(logging.WARNING, logger="components.api_worker"):
        log_pending_api_workers()

    assert "in-flight desktop request" in caplog.text

    release.set()
    assert wait_for_api_workers(5000) is True
    # Nothing pending: the exit path stays silent.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="components.api_worker"):
        log_pending_api_workers()
    assert caplog.text == ""
