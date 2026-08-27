"""Application-wide task state with durable snapshot + SSE cursor synchronization."""
from __future__ import annotations

from typing import Any

from components.api_worker import AsyncApiMixin
from components.task_stream_worker import TaskStreamWorker
from PySide6.QtCore import QObject, QSettings, QTimer, Signal


class TaskStore(QObject, AsyncApiMixin):
    """Single client-side source for tasks, onboarding, snapshots and SSE recovery."""

    changed = Signal()
    connection_changed = Signal(bool, str)
    stream_changed = Signal(bool, str)
    batch_retried = Signal(object)

    def __init__(self, api, parent=None):
        QObject.__init__(self, parent)
        self.api = api
        self._init_async_api()
        self.tasks: dict[str, dict[str, Any]] = {}
        self.summary: dict[str, Any] = {"total": 0, "active": 0, "needs_attention": 0, "by_status": {}}
        self.onboarding: dict[str, Any] = {"next_recommended_step": "select_model", "ready_model_count": 0}
        self.last_error = ""
        self._refreshing = False
        self._stream: TaskStreamWorker | None = None
        self._stream_online = False
        self._settings = QSettings("ModelForge", "Desktop")
        self._cursor_key = f"tasks/{getattr(api, 'username', 'anonymous')}/last_event_id"
        self.last_event_id = int(self._settings.value(self._cursor_key, 0) or 0)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    def start(self):
        self.refresh()
        # Periodic snapshot is the recovery source if an event is missed or history expires.
        self._timer.start(15000)

    def stop(self):
        self._timer.stop()
        stream = self._stream
        self._stream = None
        if stream and stream.isRunning():
            stream.requestInterruption()
            stream.wait(3000)
        self.shutdown_async_api()
    def active_tasks(self):
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "PARTIAL"}
        return [task for task in self.tasks.values() if task.get("status") not in terminal]

    def ordered_tasks(self):
        rank = {"WAITING_INPUT": 0, "RUNNING": 1, "CANCEL_REQUESTED": 2, "QUEUED": 3, "SCHEDULED": 4, "FAILED": 5, "PARTIAL": 6, "SUCCEEDED": 7, "CANCELLED": 8}
        return sorted(self.tasks.values(), key=lambda task: (rank.get(task.get("status"), 99), task.get("updated_at") or ""))

    def refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        self._run_api(
            lambda: (self.api.list_tasks(), self.api.task_summary(), self.api.onboarding_state()),
            self._apply_snapshot,
            self._apply_error,
        )

    def _apply_snapshot(self, result):
        tasks, summary, onboarding = result
        self.tasks = {task["task_id"]: task for task in tasks}
        self.summary = summary
        self.onboarding = onboarding
        self.last_error = ""
        self._refreshing = False
        self.connection_changed.emit(True, "")
        self.changed.emit()
        self._ensure_stream()

    def _apply_error(self, error):
        self.last_error = error
        self._refreshing = False
        self.connection_changed.emit(False, error)
        self.changed.emit()

    def _ensure_stream(self):
        if self._stream and self._stream.isRunning():
            return
        self._stream = TaskStreamWorker(self.api, self.last_event_id, self)
        self._stream.event_received.connect(self._apply_event)
        self._stream.stream_state.connect(self._stream_state)
        self._stream.resync_required.connect(self._handle_stream_resync)
        self._stream.start()

    def _stream_state(self, online, error):
        self._stream_online = online
        self.stream_changed.emit(online, error)

    def _handle_stream_resync(self, payload: dict):
        """Refresh from the persisted, user-scoped snapshot after a stream boundary."""
        try:
            cursor = int(payload.get("after_id", self.last_event_id))
        except (AttributeError, TypeError, ValueError):
            cursor = self.last_event_id
        self.last_event_id = max(self.last_event_id, cursor)
        self._settings.setValue(self._cursor_key, self.last_event_id)
        self.refresh()

    def _apply_event(self, event: dict):
        try:
            event_id = int(event.get("event_id", 0))
        except (TypeError, ValueError):
            return
        if event_id <= self.last_event_id:
            return
        task = (event.get("payload") or {}).get("task")
        if task and task.get("task_id"):
            previous = self.tasks.get(task["task_id"])
            if previous is None or int(task.get("version", 0)) >= int(previous.get("version", 0)):
                self.tasks[task["task_id"]] = task
        self.last_event_id = event_id
        self._settings.setValue(self._cursor_key, self.last_event_id)
        self._rebuild_summary()
        self.changed.emit()

    def _rebuild_summary(self):
        counts: dict[str, int] = {}
        active = 0
        for task in self.tasks.values():
            status = task.get("status", "QUEUED")
            counts[status] = counts.get(status, 0) + 1
            if status not in {"SUCCEEDED", "FAILED", "CANCELLED", "PARTIAL"}:
                active += 1
        self.summary = {
            "total": len(self.tasks),
            "active": active,
            "needs_attention": counts.get("FAILED", 0) + counts.get("PARTIAL", 0) + counts.get("WAITING_INPUT", 0),
            "by_status": counts,
        }

    def cancel(self, task_id: str, *, confirm: bool = False):
        task = self.tasks.get(task_id) or {}
        self._run_api(lambda: self.api.cancel_task(task_id, confirm=confirm, expected_version=task.get("version")), self._apply_task, self._apply_error)

    def retry(self, task_id: str, *, confirm: bool = False):
        task = self.tasks.get(task_id) or {}
        self._run_api(lambda: self.api.retry_task(task_id, confirm=confirm, expected_version=task.get("version")), self._apply_task, self._apply_error)

    def retry_many(self, task_ids: list[str], *, confirm: bool = False):
        unique_ids = list(dict.fromkeys(task_ids))
        if unique_ids:
            expected_versions = {task_id: self.tasks[task_id]["version"] for task_id in unique_ids if task_id in self.tasks and self.tasks[task_id].get("version") is not None}
            self._run_api(lambda: self.api.retry_tasks_batch(unique_ids, expected_versions=expected_versions, confirm=confirm), self._apply_batch_retry, self._apply_error)

    def _apply_batch_retry(self, result):
        for task in result.get("tasks", []):
            self.tasks[task["task_id"]] = task
        self._rebuild_summary()
        self.changed.emit()
        self.batch_retried.emit(result)
        self.refresh()

    def _apply_task(self, task):
        self.tasks[task["task_id"]] = task
        self._rebuild_summary()
        self.changed.emit()
        self.refresh()
