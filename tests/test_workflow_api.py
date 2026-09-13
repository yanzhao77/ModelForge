"""V1.5 Workflow API: CRUD, sequential/parallel/loop runs, approval, trace."""

from __future__ import annotations

import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402


def _auth(client: TestClient) -> tuple[dict, int]:
    username = f"v15{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = int(client.get("/api/v1/auth/me", headers=headers).json()["id"])
    return headers, user_id


SEQUENTIAL = {
    "entry": "start",
    "nodes": [
        {"id": "start", "type": "input", "next": "ask"},
        {"id": "ask", "type": "llm", "config": {"prompt": "{{input.question}}"}, "next": "done"},
        {"id": "done", "type": "output", "config": {"value": "{{nodes.ask.output}}"}},
    ],
}

WITH_APPROVAL = {
    "entry": "start",
    "nodes": [
        {"id": "start", "type": "input", "next": "gate"},
        {"id": "gate", "type": "approval", "config": {"message": "确认后继续"}, "next": "finish"},
        {"id": "finish", "type": "output", "config": {"value": "approved"}},
    ],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        headers, user_id = _auth(client)
        yield {"client": client, "headers": headers, "user_id": user_id}


def _create(client, headers, name, definition) -> dict:
    response = client.post(
        "/api/v1/workflows", json={"name": name, "definition": definition}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wait_for(client, headers, run_id, statuses, timeout=10.0) -> dict:
    deadline = time.monotonic() + timeout
    current = {}
    while time.monotonic() < deadline:
        current = client.get(f"/api/v1/workflows/runs/{run_id}", headers=headers).json()
        if current.get("status") in statuses:
            return current
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {statuses}: {current}")


def test_workflow_crud_and_validation(env):
    client, headers = env["client"], env["headers"]

    invalid = client.post(
        "/api/v1/workflows",
        json={"name": "broken", "definition": {"nodes": [{"id": "a", "type": "nope"}]}},
        headers=headers,
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "WORKFLOW_DEFINITION_INVALID"
    assert invalid.json()["detail"]["details"]["problems"]

    workflow = _create(client, headers, "Sequential", SEQUENTIAL)
    listed = client.get("/api/v1/workflows", headers=headers).json()
    assert [item["name"] for item in listed["workflows"]] == ["Sequential"]
    assert "parallel" in listed["node_types"]

    detail = client.get(f"/api/v1/workflows/{workflow['workflow_id']}", headers=headers)
    assert detail.json()["definition"]["entry"] == "start"

    updated = client.put(
        f"/api/v1/workflows/{workflow['workflow_id']}",
        json={"description": "updated"},
        headers=headers,
    )
    assert updated.json()["description"] == "updated"

    dry_run = client.post(
        "/api/v1/workflows/validate",
        json={"nodes": [{"id": "a", "type": "input"}, {"id": "b", "type": "ghost"}]},
        headers=headers,
    )
    assert dry_run.json()["valid"] is False

    assert client.delete(f"/api/v1/workflows/{workflow['workflow_id']}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/workflows/{workflow['workflow_id']}", headers=headers).status_code == 404


def test_workflows_are_user_scoped(env):
    client, headers = env["client"], env["headers"]
    workflow = _create(client, headers, "Private", SEQUENTIAL)
    other, _ = _auth(client)

    assert client.get(f"/api/v1/workflows/{workflow['workflow_id']}", headers=other).status_code == 404
    assert client.get("/api/v1/workflows", headers=other).json()["workflows"] == []


def test_sequential_run_produces_output_events_and_trace(env):
    client, headers = env["client"], env["headers"]
    workflow = _create(client, headers, "Sequential run", SEQUENTIAL)

    started = client.post(
        f"/api/v1/workflows/{workflow['workflow_id']}/runs",
        json={"input": {"question": "你好"}, "confirm": True},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    run = _wait_for(client, headers, run_id, {"COMPLETED", "FAILED"})

    assert run["status"] == "COMPLETED", run
    assert run["output"] == "[echo] 你好"
    assert run["state"]["nodes"]["ask"]["status"] == "COMPLETED"

    events = client.get(f"/api/v1/workflows/runs/{run_id}/events", headers=headers).json()["events"]
    types = [event["event_type"] for event in events]
    assert "workflow.run.started" in types
    assert "workflow.node.completed" in types
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)

    trace = client.get(f"/api/v1/workflows/runs/{run_id}/trace", headers=headers).json()
    assert trace["trace_id"] == run_id
    assert trace["status"] == "COMPLETED"
    assert trace["summary"]["node_count"] >= 3
    assert any(span["type"] == "run" for span in trace["spans"])
    assert any(span["name"].startswith("workflow.node.ask") for span in trace["spans"])

    runs = client.get(f"/api/v1/workflows/{workflow['workflow_id']}/runs", headers=headers).json()["runs"]
    assert [item["run_id"] for item in runs] == [run_id]


def test_parallel_loop_and_condition_run_together(env):
    client, headers = env["client"], env["headers"]
    definition = {
        "entry": "start",
        "nodes": [
            {"id": "start", "type": "input", "next": "fan"},
            {"id": "fan", "type": "parallel", "branches": [["p1"], ["p2"]], "next": "check"},
            {"id": "p1", "type": "llm", "config": {"prompt": "alpha"}},
            {"id": "p2", "type": "llm", "config": {"prompt": "beta"}},
            {
                "id": "check",
                "type": "condition",
                "config": {"expression": "'alpha' in nodes.p1.output"},
                "true_next": "repeat",
                "false_next": "done",
            },
            {
                "id": "repeat",
                "type": "loop",
                "body": ["tick"],
                "config": {"max_iterations": 3, "while": "variables.loop_iteration < 2"},
                "next": "done",
            },
            {"id": "tick", "type": "llm", "config": {"prompt": "tick"}},
            {"id": "done", "type": "output", "config": {"value": "{{nodes.fan.output}}"}},
        ],
    }
    workflow = _create(client, headers, "Parallel loop", definition)

    run_id = client.post(
        f"/api/v1/workflows/{workflow['workflow_id']}/runs", json={"input": {}, "confirm": True}, headers=headers
    ).json()["run_id"]
    run = _wait_for(client, headers, run_id, {"COMPLETED", "FAILED"})

    assert run["status"] == "COMPLETED", run
    assert len(run["state"]["nodes"]["fan"]["output"]["branches"]) == 2
    assert run["state"]["nodes"]["repeat"]["output"]["iterations"] == 2
    assert run["state"]["nodes"]["check"]["output"]["value"] is True


def test_human_approval_pauses_and_resumes(env):
    client, headers = env["client"], env["headers"]
    workflow = _create(client, headers, "Approval", WITH_APPROVAL)

    run_id = client.post(
        f"/api/v1/workflows/{workflow['workflow_id']}/runs", json={"input": {}, "confirm": True}, headers=headers
    ).json()["run_id"]
    paused = _wait_for(client, headers, run_id, {"WAITING_HUMAN", "FAILED"})
    assert paused["status"] == "WAITING_HUMAN", paused
    assert paused["state"]["nodes"]["gate"]["status"] == "WAITING_HUMAN"

    approved = client.post(f"/api/v1/workflows/runs/{run_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    completed = _wait_for(client, headers, run_id, {"COMPLETED", "FAILED"})
    assert completed["status"] == "COMPLETED", completed
    assert completed["output"] == "approved"

    events = client.get(f"/api/v1/workflows/runs/{run_id}/events", headers=headers).json()["events"]
    types = [event["event_type"] for event in events]
    assert "workflow.approval.required" in types
    assert "workflow.approval.granted" in types


def test_cancel_and_run_confirmation(env):
    client, headers = env["client"], env["headers"]
    workflow = _create(client, headers, "Cancel", WITH_APPROVAL)

    unconfirmed = client.post(
        f"/api/v1/workflows/{workflow['workflow_id']}/runs",
        json={"input": {}, "confirm": False},
        headers=headers,
    )
    assert unconfirmed.status_code == 409

    run_id = client.post(
        f"/api/v1/workflows/{workflow['workflow_id']}/runs", json={"input": {}, "confirm": True}, headers=headers
    ).json()["run_id"]
    _wait_for(client, headers, run_id, {"WAITING_HUMAN", "FAILED"})

    cancelled = client.post(f"/api/v1/workflows/runs/{run_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    # Approving a cancelled run is rejected instead of silently resuming it.
    assert client.post(f"/api/v1/workflows/runs/{run_id}/approve", headers=headers).status_code == 409
