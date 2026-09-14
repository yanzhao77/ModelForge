"""V4.0 unified OS API coverage."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402


def _auth(client: TestClient) -> dict:
    username = f"v40{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": f"{username}@example.test"})
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _model(client: TestClient, headers: dict) -> int:
    model_dir = Path(__file__).resolve().parents[1] / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    asset = model_dir / f"os-{uuid.uuid4().hex}.gguf"
    asset.write_bytes(b"GGUF")
    response = client.post("/api/v1/models/install", json={"name": f"os-model-{uuid.uuid4().hex[:8]}", "provider": "local", "path": str(asset)}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_v4_resources_processes_events_and_skills():
    with TestClient(app) as client:
        headers = _auth(client)
        model_id = _model(client, headers)
        agent = client.post("/api/v1/agents", json={"name": "os-agent", "model_id": model_id}, headers=headers)
        assert agent.status_code == 200, agent.text

        resources = client.get("/api/v1/resources", params={"type": "agent"}, headers=headers)
        assert resources.status_code == 200, resources.text
        assert any(item["resource_id"] == "os-agent" and item["type"] == "agent" for item in resources.json()["resources"])

        task = client.post("/api/v1/tasks", json={"task_type": "manual", "title": "OS task"}, headers=headers)
        assert task.status_code == 200, task.text
        processes = client.get("/api/v1/processes", headers=headers)
        assert processes.status_code == 200, processes.text
        assert any(item["process_id"] == task.json()["task_id"] and item["type"] == "task" for item in processes.json()["processes"])

        event = client.post("/api/v1/os/events", json={"event_type": "goal.created", "subject_id": "demo", "payload": {"ok": True}}, headers=headers)
        assert event.status_code == 200, event.text
        listed = client.get("/api/v1/os/events", params={"event_type": "goal.created"}, headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["events"][0]["payload"] == {"ok": True}

        skill = client.post("/api/v1/skills", json={"name": "Python Development", "tools": ["file_search", "python"], "prompt": "Build and test."}, headers=headers)
        assert skill.status_code == 200, skill.text
        assert skill.json()["tools"] == ["file_search", "python"]

        dashboard = client.get("/api/v1/dashboard/v4", headers=headers)
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["resources"].get("agent", 0) >= 1
