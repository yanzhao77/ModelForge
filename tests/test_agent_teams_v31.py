"""V3.1 Multi-Agent Team API and trace coverage."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402


def _auth(client: TestClient) -> dict:
    username = f"v31{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _agent(client: TestClient, headers: dict, name: str, model_id: int) -> None:
    response = client.post(
        "/api/v1/agents",
        json={"name": name, "model_id": model_id, "tools": [], "system_prompt": f"You are {name}."},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _model(client: TestClient, headers: dict) -> int:
    model_dir = Path(__file__).resolve().parents[1] / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    asset = model_dir / f"team-{uuid.uuid4().hex}.gguf"
    asset.write_bytes(b"GGUF")
    response = client.post(
        "/api/v1/models/install",
        json={"name": f"team-model-{uuid.uuid4().hex[:8]}", "provider": "local", "path": str(asset)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_agent_team_create_run_and_trace():
    with TestClient(app) as client:
        headers = _auth(client)
        model_id = _model(client, headers)
        for name in ["manager", "researcher", "coder", "tester", "reviewer"]:
            _agent(client, headers, name, model_id)

        created = client.post(
            "/api/v1/agent-teams",
            json={
                "name": "Release Team",
                "description": "Sequential delivery team",
                "manager_agent_id": "manager",
                "strategy": "SEQUENTIAL",
                "members": [
                    {"agent_id": "researcher", "role": "RESEARCHER"},
                    {"agent_id": "coder", "role": "CODER"},
                    {"agent_id": "tester", "role": "TESTER"},
                    {"agent_id": "reviewer", "role": "REVIEWER"},
                ],
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        team = created.json()
        assert team["manager_agent_id"] == "manager"
        assert {member["role"] for member in team["members"]} >= {"MANAGER", "RESEARCHER", "CODER", "TESTER", "REVIEWER"}

        run = client.post(
            f"/api/v1/agent-teams/{team['team_id']}/runs",
            json={"input": "Build the next release checklist", "execute": False},
            headers=headers,
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["team_id"] == team["team_id"]
        assert body["status"] == "PENDING"
        assert [task["role"] for task in body["tasks"]] == ["RESEARCHER", "CODER", "TESTER", "REVIEWER"]

        first_task_id = body["tasks"][0]["task_id"]
        task = client.get(f"/api/v1/agent-tasks/{first_task_id}", headers=headers)
        assert task.status_code == 200
        assert task.json()["agent_id"] == "researcher"

        trace = client.get(f"/api/v1/agent-teams/{team['team_id']}/runs/{body['run_id']}/trace", headers=headers)
        assert trace.status_code == 200, trace.text
        event_types = [event["event_type"] for event in trace.json()["events"]]
        assert "team.started" in event_types
        assert event_types.count("task.created") == 4
        assert trace.json()["messages"][0]["message_type"] == "REQUEST"

        exported = client.post(
            "/api/v1/packages/export",
            json={"kind": "team", "ref": team["team_id"], "version": "1.0.0"},
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        document = exported.json()
        assert document["manifest"]["kind"] == "team"
        assert {item["kind"] for item in document["manifest"]["requires"]} == {"agent"}

        search = client.get("/api/v1/marketplace", params={"kind": "team", "query": "Release"}, headers=headers)
        assert search.status_code == 200, search.text
        assert search.json()["items"][0]["package_id"] == document["manifest"]["package_id"]

        detail = client.get(f"/api/v1/marketplace/{document['manifest']['package_id']}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["security_scan"]["status"] == "passed"


def test_agent_delegate_endpoint_creates_task():
    with TestClient(app) as client:
        headers = _auth(client)
        model_id = _model(client, headers)
        _agent(client, headers, "manager-delegate", model_id)
        _agent(client, headers, "writer-delegate", model_id)

        response = client.post(
            "/api/v1/agents/manager-delegate/delegate",
            json={"delegate_agent_id": "writer-delegate", "instruction": "Draft the user-facing summary"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["delegation"]["manager_agent_id"] == "manager-delegate"
        assert body["delegation"]["delegate_agent_id"] == "writer-delegate"
        assert body["task"]["task_type"] == "agent_delegation"

        cancel = client.post(
            f"/api/v1/agent-tasks/{body['task']['task_id']}/cancel",
            json={"confirm": True},
            headers=headers,
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "CANCELLED"
