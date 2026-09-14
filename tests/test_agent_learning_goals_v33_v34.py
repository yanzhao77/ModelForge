"""V3.3 Agent Learning and V3.4 Goal API coverage."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402


def _auth(client: TestClient) -> dict:
    username = f"v34{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _model(client: TestClient, headers: dict) -> int:
    model_dir = Path(__file__).resolve().parents[1] / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    asset = model_dir / f"learning-{uuid.uuid4().hex}.gguf"
    asset.write_bytes(b"GGUF")
    response = client.post(
        "/api/v1/models/install",
        json={"name": f"learning-model-{uuid.uuid4().hex[:8]}", "provider": "local", "path": str(asset)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _agent(client: TestClient, headers: dict, name: str, model_id: int) -> None:
    response = client.post("/api/v1/agents", json={"name": name, "model_id": model_id}, headers=headers)
    assert response.status_code == 200, response.text


def test_agent_experience_record_and_recommend():
    with TestClient(app) as client:
        headers = _auth(client)
        model_id = _model(client, headers)
        _agent(client, headers, "learning-agent", model_id)

        created = client.post(
            "/api/v1/agent-experiences",
            json={
                "agent_id": "learning-agent",
                "goal": "prepare release checklist",
                "strategy": {"mode": "sequential"},
                "steps": [{"action": "inspect plan", "observation": "found phases"}],
                "tools": ["file_search"],
                "result": {"done": True},
                "outcome": "SUCCESS",
                "score": 0.9,
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["outcome"] == "SUCCESS"
        assert "What worked?" in body["reflection"]

        recommended = client.post(
            "/api/v1/agent-experiences/recommend",
            json={"agent_id": "learning-agent", "goal": "prepare a release checklist", "limit": 3},
            headers=headers,
        )
        assert recommended.status_code == 200, recommended.text
        assert recommended.json()["recommendations"][0]["experience_id"] == body["experience_id"]
        assert "system_code_change" in recommended.json()["policy"]["blocked"]


def test_goal_decomposition_and_approval_flow():
    with TestClient(app) as client:
        headers = _auth(client)
        model_id = _model(client, headers)
        _agent(client, headers, "goal-agent", model_id)

        goal = client.post(
            "/api/v1/goals",
            json={
                "agent_id": "goal-agent",
                "title": "Weekly model operations report",
                "description": "Create and review a recurring operational report.",
                "success_criteria": ["report generated", "review completed"],
            },
            headers=headers,
        )
        assert goal.status_code == 200, goal.text
        goal_body = goal.json()
        assert goal_body["status"] == "PLANNED"
        assert [item["title"] for item in goal_body["sub_goals"]] == ["Observe", "Plan", "Execute", "Evaluate", "Reflect"]

        approval = client.post(
            "/api/v1/approvals",
            json={"agent_id": "goal-agent", "goal_id": goal_body["goal_id"], "action": "execute shell command", "risk": "HIGH"},
            headers=headers,
        )
        assert approval.status_code == 200, approval.text
        approval_body = approval.json()
        assert approval_body["status"] == "PENDING"

        decision = client.post(
            f"/api/v1/approvals/{approval_body['approval_id']}/decision",
            json={"decision": "MODIFY", "modifications": {"command": "pytest -q"}, "comment": "limit scope"},
            headers=headers,
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["approval"]["status"] == "MODIFIED"
