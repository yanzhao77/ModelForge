"""Unit coverage for desktop TaskStore durable SSE event application."""
import os
import sys
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from PySide6.QtCore import QCoreApplication
from components.task_store import TaskStore


class FakeApi:
    username = f"stream-test-{uuid.uuid4().hex}"


def task(task_id="task-1", status="RUNNING", version=1):
    return {
        "task_id": task_id, "title": "下载示例模型", "status": status, "version": version,
        "source": "downloader", "summary": "同步中", "cancelable": True,
    }


def test_task_store_applies_cursor_events_idempotently_and_rebuilds_summary():
    app = QCoreApplication.instance() or QCoreApplication([])
    store = TaskStore(FakeApi())
    store.last_event_id = 10

    store._apply_event({"event_id": 11, "payload": {"task": task()}})
    assert store.last_event_id == 11
    assert store.tasks["task-1"]["status"] == "RUNNING"
    assert store.summary["active"] == 1

    # Duplicate cursor is ignored even if it carries a conflicting payload.
    store._apply_event({"event_id": 11, "payload": {"task": task(status="FAILED", version=2)}})
    assert store.tasks["task-1"]["status"] == "RUNNING"

    store._apply_event({"event_id": 12, "payload": {"task": task(status="FAILED", version=2)}})
    assert store.tasks["task-1"]["status"] == "FAILED"
    assert store.summary["active"] == 0
    assert store.summary["needs_attention"] == 1

    # Newer event ID with an older entity version cannot roll task state back.
    store._apply_event({"event_id": 13, "payload": {"task": task(status="RUNNING", version=1)}})
    assert store.tasks["task-1"]["status"] == "FAILED"
    assert store.last_event_id == 13
    app.processEvents()
