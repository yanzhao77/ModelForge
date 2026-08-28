"""Integration tests for the persisted global task center API."""
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth(client, prefix):
    username = f"{prefix}-{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": f"{username}@example.com"})
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def create_task(client, headers, **overrides):
    payload = {
        "task_type": "knowledge_ingest",
        "source": "knowledge",
        "title": "产品手册.pdf",
        "summary": "等待解析",
        "metadata": {"filename": "产品手册.pdf"},
        "cancelable": True,
        "retryable": True,
    }
    payload.update(overrides)
    response = client.post("/api/v1/tasks", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_task_routes_require_authentication(client):
    assert client.get("/api/v1/tasks").status_code == 401
    assert client.get("/api/v1/tasks/summary").status_code == 401
    assert client.get("/api/v1/tasks/onboarding/state").status_code == 401


def test_task_lifecycle_events_and_summary(client):
    headers = auth(client, "tasklife")
    task = create_task(client, headers)
    assert task["status"] == "QUEUED"
    assert task["cancelable"] is True

    started = client.post(
        f"/api/v1/tasks/{task['task_id']}/transition",
        json={"status": "RUNNING", "progress_percent": 25, "summary": "正在分块"},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "RUNNING"
    assert started.json()["progress_percent"] == 25

    events = client.get(f"/api/v1/tasks/{task['task_id']}/events", headers=headers)
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()["events"]] == ["task.created", "task.updated"]

    summary = client.get("/api/v1/tasks/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["active"] >= 1

    cancelled = client.post(f"/api/v1/tasks/{task['task_id']}/cancel", json={"confirm": True}, headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCEL_REQUESTED"


def test_tasks_are_isolated_by_user_and_support_idempotency(client):
    alice = auth(client, "taskalice")
    bob = auth(client, "taskbob")
    key = uuid.uuid4().hex
    first = create_task(client, alice, title="alice-private", idempotency_key=key)
    duplicate = create_task(client, alice, title="ignored-duplicate", idempotency_key=key)
    assert duplicate["task_id"] == first["task_id"]

    alice_tasks = client.get("/api/v1/tasks", headers=alice).json()["tasks"]
    bob_tasks = client.get("/api/v1/tasks", headers=bob).json()["tasks"]
    assert any(item["task_id"] == first["task_id"] for item in alice_tasks)
    assert all(item["task_id"] != first["task_id"] for item in bob_tasks)
    assert client.get(f"/api/v1/tasks/{first['task_id']}", headers=bob).status_code == 404


def test_onboarding_state_reflects_authenticated_user(client):
    headers = auth(client, "taskonboard")
    response = client.get("/api/v1/tasks/onboarding/state", headers=headers)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["server_connected"] is True
    assert state["next_recommended_step"] in {"select_model", "send_message", "run_agent", "complete"}


def test_failed_retryable_task_creates_auditable_queued_child(client):
    headers = auth(client, "taskretry")
    failed = create_task(client, headers, title="网络抓取", retryable=True)
    transitioned = client.post(
        f"/api/v1/tasks/{failed['task_id']}/transition",
        headers=headers,
        json={"status": "FAILED", "error_message": "upstream timeout"},
    )
    assert transitioned.status_code == 200, transitioned.text
    retried = client.post(f"/api/v1/tasks/{failed['task_id']}/retry", json={"confirm": True}, headers=headers)
    assert retried.status_code == 200, retried.text
    payload = retried.json()
    assert payload["status"] == "QUEUED"
    assert payload["parent_task_id"] == failed["task_id"]
    assert payload["attempt"] == 2
    events = client.get(f"/api/v1/tasks/{failed['task_id']}/events", headers=headers).json()["events"]
    assert any(event["event_type"] == "task.retry_requested" for event in events)

    non_retryable = create_task(client, headers, title="不可重试", retryable=False)
    client.post(f"/api/v1/tasks/{non_retryable['task_id']}/transition", headers=headers, json={"status": "FAILED"})
    blocked = client.post(f"/api/v1/tasks/{non_retryable['task_id']}/retry", json={"confirm": True}, headers=headers)
    assert blocked.status_code == 400


def test_retry_dispatch_failure_is_auditable_and_exposes_logs(client):
    headers = auth(client, "retrydispatch")
    failed = create_task(
        client,
        headers,
        task_type="model_download",
        source="download",
        title="缺失下载参数",
        metadata={},
    )
    transition = client.post(
        f"/api/v1/tasks/{failed['task_id']}/transition",
        headers=headers,
        json={"status": "FAILED", "error_message": "network unavailable"},
    )
    assert transition.status_code == 200, transition.text

    retried = client.post(f"/api/v1/tasks/{failed['task_id']}/retry", json={"confirm": True}, headers=headers)
    assert retried.status_code == 200, retried.text
    retry_payload = retried.json()
    assert retry_payload["status"] == "FAILED"
    assert retry_payload["error_code"] == "RETRY_DISPATCH_FAILED"
    assert "repo_id" in retry_payload["error_message"]

    logs = client.get(f"/api/v1/tasks/{retry_payload['task_id']}/logs", headers=headers)
    assert logs.status_code == 200, logs.text
    assert logs.json() == {"source": "downloader", "lines": []}
    events = client.get(f"/api/v1/tasks/{retry_payload['task_id']}/events", headers=headers).json()["events"]
    assert [event["event_type"] for event in events] == ["task.created", "task.updated"]


def test_batch_retry_returns_per_task_success_and_failure(client):
    headers = auth(client, "batchretry")
    retryable = create_task(client, headers, title="允许批量重试", retryable=True)
    blocked = create_task(client, headers, title="不可批量重试", retryable=False)
    for task in (retryable, blocked):
        response = client.post(
            f"/api/v1/tasks/{task['task_id']}/transition",
            headers=headers,
            json={"status": "FAILED", "error_message": "executor failed"},
        )
        assert response.status_code == 200, response.text

    result = client.post(
        "/api/v1/tasks/retry-batch",
        headers=headers,
        json={"task_ids": [retryable["task_id"], retryable["task_id"], blocked["task_id"], "not-owned"], "confirm": True},
    )
    assert result.status_code == 200, result.text
    payload = result.json()
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["parent_task_id"] == retryable["task_id"]
    failures = {item["task_id"]: item["code"] for item in payload["failures"]}
    assert failures[blocked["task_id"]] == "TASK_NOT_RETRYABLE"
    assert failures["not-owned"] == "TASK_UNAVAILABLE"
