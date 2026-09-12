"""Task-center retry must actually execute the owning agent run."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid

from fastapi.testclient import TestClient

_tmp_db = tempfile.mkdtemp(prefix="mf_taskretry_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ.setdefault("JWT_SECRET", "task-retry-test-secret-0123456789")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402
from runtime.models import MockProvider  # noqa: E402
from runtime.types import AgentConfig  # noqa: E402
from services.agent_runtime_service import get_agent_runtime  # noqa: E402


def _wait_status(client: TestClient, headers: dict, run_id: str, expected: set[str], attempts: int = 60) -> str:
    status = ""
    for _ in range(attempts):
        status = client.get(f"/api/v1/agent/runs/{run_id}", headers=headers).json()["status"]
        if status in expected:
            return status
        time.sleep(0.1)
    return status


def _task_row(client: TestClient, headers: dict, run_id: str) -> dict:
    tasks = client.get("/api/v1/tasks", headers=headers).json()["tasks"]
    return next(task for task in tasks if task.get("source_task_id") == run_id)


def test_retrying_a_failed_agent_run_executes_again(monkeypatch):
    async def failing_engine(ctx, provider):
        raise RuntimeError("first attempt failed")

    async def succeeding_engine(ctx, provider):
        return {
            "status": "COMPLETED",
            "output": "retried ok",
            "error": None,
            "iteration": 1,
            "tool_call_count": 0,
            "token_usage": {},
            "messages": [],
        }

    with TestClient(app) as client:
        runtime = get_agent_runtime()
        assert runtime is not None
        monkeypatch.setattr(runtime, "provider_factory", lambda model: MockProvider(script=[MockProvider.final("ok")]))
        username = f"taskretry-{uuid.uuid4().hex[:8]}"
        client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
        )
        token = client.post(
            "/api/v1/auth/login", json={"username": username, "password": "secret123"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
        agent = f"retry-bot-{uuid.uuid4().hex[:6]}"
        runtime.create_agent(AgentConfig(name=agent, model="mock", user_id=user_id, tools=[]))

        monkeypatch.setattr(runtime.engine, "execute", failing_engine)
        started = client.post(
            "/api/v1/agent/runs",
            json={"agent_id": agent, "input": "hi", "execute": True, "confirm": True},
            headers=headers,
        )
        run_id = started.json()["run_id"]
        assert _wait_status(client, headers, run_id, {"FAILED"}) == "FAILED"

        monkeypatch.setattr(runtime.engine, "execute", succeeding_engine)
        row = _task_row(client, headers, run_id)
        assert row["status"] == "FAILED"
        assert row["retryable"] is True

        retried = client.post(
            f"/api/v1/tasks/{row['task_id']}/retry", json={"confirm": True}, headers=headers
        )
        assert retried.status_code == 200, retried.text
        child = retried.json()
        assert child["error_code"] is None
        assert child["status"] == "RUNNING"

        child_run_id = child["metadata"]["execution_task_id"]
        assert _wait_status(client, headers, child_run_id, {"COMPLETED"}) == "COMPLETED"
