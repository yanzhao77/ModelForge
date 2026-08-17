"""Regression tests for non-blocking PySide6 API task execution."""
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client" / "pyside6"))

from components.api_worker import ApiWorker


def test_api_worker_executes_blocking_operation_off_gui_thread():
    app = QCoreApplication.instance() or QCoreApplication([])
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
