"""DB outbox dispatcher and in-process notifier for task SSE streams.

The database event table remains the source of truth. The notifier only reduces
latency; clients always replay TaskEvent rows from their last cursor on reconnect.
"""
from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from core.database import SessionLocal
from models.records import TaskOutbox


class TaskEventHub:
    def __init__(self):
        self._condition = threading.Condition()
        self._latest_by_user: dict[int, int] = defaultdict(int)

    def publish(self, user_id: int, event_id: int) -> None:
        with self._condition:
            self._latest_by_user[user_id] = max(self._latest_by_user[user_id], event_id)
            self._condition.notify_all()

    def wait_for_user(self, user_id: int, after_id: int, timeout: float = 10.0) -> bool:
        with self._condition:
            if self._latest_by_user.get(user_id, 0) > after_id:
                return True
            self._condition.wait(timeout=max(0.1, timeout))
            return self._latest_by_user.get(user_id, 0) > after_id


task_event_hub = TaskEventHub()


class TaskOutboxPublisher:
    """Poll committed outbox rows and publish wake-up notifications safely.

    Marking is intentionally at-least-once: an interrupted process may wake a
    client twice, but SSE event IDs make duplicate application idempotent.
    """

    def __init__(self, poll_interval: float = 0.15, batch_size: int = 100, lease_seconds: float = 15.0):
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="task-outbox-publisher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def nudge(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.dispatch_once()
            self._wake.wait(self.poll_interval)
            self._wake.clear()

    def dispatch_once(self) -> int:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            rows = (
                db.query(TaskOutbox)
                .filter(
                    TaskOutbox.dispatched_at.is_(None),
                    (TaskOutbox.lease_expires_at.is_(None) | (TaskOutbox.lease_expires_at < now)),
                    (TaskOutbox.next_attempt_at.is_(None) | (TaskOutbox.next_attempt_at <= now)),
                )
                .order_by(TaskOutbox.id.asc())
                .limit(self.batch_size)
                .all()
            )
            if not rows:
                return 0
            claimed = []
            for row in rows:
                token = uuid.uuid4().hex
                row.lease_token = token
                row.lease_expires_at = now + timedelta(seconds=max(1.0, self.lease_seconds))
                claimed.append((row.id, token))
            db.commit()
            delivered = 0
            for row_id, token in claimed:
                row = (
                    db.query(TaskOutbox)
                    .filter(TaskOutbox.id == row_id, TaskOutbox.lease_token == token, TaskOutbox.dispatched_at.is_(None))
                    .first()
                )
                if row is None:
                    continue
                row.attempts += 1
                try:
                    task_event_hub.publish(row.user_id, row.event_id)
                    row.dispatched_at = datetime.utcnow()
                    row.last_error = None
                    row.lease_token = None
                    row.lease_expires_at = None
                    row.next_attempt_at = None
                    delivered += 1
                except Exception as exc:  # Keep row pending for a later attempt.
                    row.last_error = str(exc)[:2000]
                    row.lease_token = None
                    row.lease_expires_at = None
                    row.next_attempt_at = datetime.utcnow() + timedelta(seconds=self._backoff_seconds(row.attempts))
            db.commit()
            return delivered
        except Exception:
            db.rollback()
            return 0
        finally:
            db.close()

    @staticmethod
    def _backoff_seconds(attempts: int) -> float:
        """Bound retry delay so a failing notifier cannot spin on one row."""
        return min(30.0, 0.25 * (2 ** min(7, max(0, attempts - 1))))


task_outbox_publisher = TaskOutboxPublisher()
