"""Unit coverage for desktop TaskStore durable SSE event application."""
import os
import sys
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from components.task_store import TaskStore
from components.task_stream_worker import normalize_task_event
from PySide6.QtCore import QCoreApplication


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


def test_task_stream_event_is_normalized_for_task_store_contract():
    raw = {"id": "21", "event": "task.updated", "payload": task(version=4)}

    normalized = normalize_task_event(raw)

    assert normalized == {
        "event_id": 21,
        "event_type": "task.updated",
        "payload": {"task": task(version=4)},
    }


def test_task_stream_event_rejects_missing_cursor_or_payload():
    assert normalize_task_event({"payload": task()}) is None
    assert normalize_task_event({"id": "7", "payload": "not-a-task"}) is None


def test_task_store_applies_batch_retry_result_and_emits_summary():
    app = QCoreApplication.instance() or QCoreApplication([])
    store = TaskStore(FakeApi())
    store.refresh = lambda: None
    received = []
    store.batch_retried.connect(received.append)
    result = {
        "tasks": [task(task_id="retry-task-1", status="QUEUED", version=1)],
        "failures": [{"task_id": "task-2", "code": "TASK_NOT_RETRYABLE", "message": "任务不可重试"}],
    }
    store._apply_batch_retry(result)
    assert store.tasks["retry-task-1"]["status"] == "QUEUED"
    assert received == [result]
    app.processEvents()




def test_task_center_only_marks_failures_with_remaining_retry_budget():
    from components.task_center import TaskCenterDock

    assert TaskCenterDock._can_retry({"status": "FAILED", "retryable": True, "attempt": 1, "max_attempts": 3})
    assert not TaskCenterDock._can_retry({"status": "FAILED", "retryable": True, "attempt": 3, "max_attempts": 3})
    assert not TaskCenterDock._can_retry({"status": "RUNNING", "retryable": True, "attempt": 1, "max_attempts": 3})
