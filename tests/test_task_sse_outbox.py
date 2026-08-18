"""End-to-end verification of task DB outbox publication and SSE cursor recovery."""
import asyncio
import json
import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from api.tasks import stream_tasks
from core.database import SessionLocal
from main import app
from models.records import TaskOutbox


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth(client):
    username = f"sse-{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": f"{username}@example.com"})
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def create_task(client, headers):
    response = client.post("/api/v1/tasks", headers=headers, json={
        "task_type": "model_download", "source": "downloader", "title": "test-model",
        "cancelable": True, "retryable": True, "metadata": {"repo": "org/test"},
    })
    assert response.status_code == 200, response.text
    return response.json()


def read_sse_event(response):
    """Consume one chunk directly from StreamingResponse's async iterator.

    TestClient intentionally buffers never-ending SSE responses. Directly
    exercising the response iterator still covers the routed API's durable
    cursor serialization without waiting for a stream to close.
    """
    raw = asyncio.run(response.body_iterator.__anext__())
    text = raw.decode() if isinstance(raw, bytes) else raw
    event = {}
    for line in text.splitlines():
        if not line or line.startswith(":"):
            continue
        key, value = line.split(":", 1)
        event[key] = value.strip()
    return event


def user_for_headers(headers):
    db = SessionLocal()
    try:
        from models.records import User
        token = headers["Authorization"].split(" ", 1)[1]
        # Tokens carry a unique username in this test setup; resolve through /me is
        # avoided so the stream endpoint can be called with its injected user object.
        from core.security import decode_token
        payload = decode_token(token) or {}
        return db.query(User).filter_by(id=int(payload.get("sub", "0"))).first()
    finally:
        db.close()


def test_sse_cursor_replays_task_events_and_outbox_dispatches(client):
    headers = auth(client)
    task = create_task(client, headers)

    user = user_for_headers(headers)
    first = read_sse_event(stream_tasks(after_id=0, last_event_id=None, user=user))
    assert first["event"] == "task.created"
    payload = json.loads(first["data"])
    assert payload["task_id"] == task["task_id"]
    first_id = int(first["id"])

    updated = client.post(
        f"/api/v1/tasks/{task['task_id']}/transition",
        headers=headers,
        json={"status": "RUNNING", "progress_percent": 40, "expected_version": 1},
    )
    assert updated.status_code == 200, updated.text

    second = read_sse_event(stream_tasks(after_id=0, last_event_id=str(first_id), user=user))
    assert second["event"] == "task.updated"
    second_payload = json.loads(second["data"])
    assert second_payload["task_id"] == task["task_id"]
    assert int(second["id"]) > first_id

    deadline = time.time() + 2.0
    dispatched = False
    while time.time() < deadline:
        db = SessionLocal()
        try:
            rows = db.query(TaskOutbox).all()
            dispatched = bool(rows) and all(row.dispatched_at is not None for row in rows if row.event_id in {first_id, int(second["id"])})
        finally:
            db.close()
        if dispatched:
            break
        time.sleep(0.05)
    assert dispatched, "committed task events should be acknowledged by the DB outbox publisher"
