"""Task-center cancel must reach the executor that owns the work."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

_tmp_db = tempfile.mkdtemp(prefix="mf_taskcancel_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ.setdefault("JWT_SECRET", "task-cancel-test-secret-0123456789")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402
from runtime.models import MockProvider  # noqa: E402
from runtime.types import AgentConfig  # noqa: E402
from services.agent_runtime_service import get_agent_runtime  # noqa: E402


def _account(client: TestClient, label: str) -> tuple[dict, int]:
    username = f"{label}-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["token"]}
    return headers, login.json()["user"]["id"]


def _task_row(client: TestClient, headers: dict, source_task_id: str) -> dict:
    tasks = client.get("/api/v1/tasks", headers=headers).json()["tasks"]
    return next(task for task in tasks if task.get("source_task_id") == source_task_id)


def test_task_center_cancel_stops_a_running_agent_run(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    async def blocking_execute(ctx, provider):
        entered.set()
        await asyncio.to_thread(release.wait, 10)
        return {
            "status": "COMPLETED",
            "output": "done",
            "error": None,
            "iteration": 1,
            "tool_call_count": 0,
            "token_usage": {},
            "messages": [],
        }

    try:
        with TestClient(app) as client:
            runtime = get_agent_runtime()
            assert runtime is not None
            monkeypatch.setattr(runtime, "provider_factory", lambda model: MockProvider(script=[MockProvider.final("x")]))
            monkeypatch.setattr(runtime.engine, "execute", blocking_execute)
            headers, user_id = _account(client, "taskcancel")
            agent = f"cancel-bot-{uuid.uuid4().hex[:6]}"
            runtime.create_agent(AgentConfig(name=agent, model="mock", user_id=user_id, tools=[]))
            started = client.post(
                "/api/v1/agent/runs",
                json={"agent_id": agent, "input": "hi", "execute": True, "confirm": True},
                headers=headers,
            )
            assert started.status_code == 200, started.text
            run_id = started.json()["run_id"]
            assert entered.wait(10), "the Agent Run never started executing"

            row = _task_row(client, headers, run_id)
            assert row["status"] == "RUNNING"
            cancelled = client.post(
                f"/api/v1/tasks/{row['task_id']}/cancel", json={"confirm": True}, headers=headers
            )
            assert cancelled.status_code == 200, cancelled.text

            run_status = None
            for _ in range(50):
                run_status = client.get(f"/api/v1/agent/runs/{run_id}", headers=headers).json()["status"]
                if run_status == "CANCELLED":
                    break
                time.sleep(0.1)
            assert run_status == "CANCELLED"

            settled = _task_row(client, headers, run_id)
            assert settled["status"] == "CANCELLED"
    finally:
        release.set()


def test_task_center_cancel_stops_a_running_training(monkeypatch, tmp_path):
    import services.training as training

    monkeypatch.setattr(training, "_torch_available", lambda: True)
    monkeypatch.setattr(training.TrainingService, "POLL_INTERVAL", 0.1)
    monkeypatch.setattr(training.settings, "train_output_dir", str(tmp_path / "outputs"))

    def fake_launch(self, cfg_path, state_path, log_path):
        from unittest.mock import MagicMock

        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("started\n")
        process = MagicMock()
        process.poll.return_value = None
        process.returncode = None
        process.terminate = MagicMock()
        return process

    monkeypatch.setattr(training.TrainingService, "_launch", fake_launch)
    dataset = tmp_path / "train.jsonl"
    dataset.write_text('{"text": "hello"}\n', encoding="utf-8")

    with TestClient(app) as client:
        headers, _user_id = _account(client, "taskcanceltrain")
        started = client.post(
            "/api/v1/train/start",
            json={"dataset_path": str(dataset), "base_model": "mock-base", "confirm": True},
            headers=headers,
        )
        assert started.status_code == 200, started.text
        train_task_id = started.json()["task_id"]

        row = _task_row(client, headers, train_task_id)
        cancelled = client.post(
            f"/api/v1/tasks/{row['task_id']}/cancel", json={"confirm": True}, headers=headers
        )
        assert cancelled.status_code == 200, cancelled.text

        assert client.get(f"/api/v1/train/status/{train_task_id}", headers=headers).json()["status"] == "stopped"
        settled = _task_row(client, headers, train_task_id)
        assert settled["status"] == "CANCELLED"
