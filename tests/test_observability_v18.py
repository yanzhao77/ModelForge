"""V1.8 Observability / Evaluation / Secret backend."""

from __future__ import annotations

import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import services.model_runtime_manager as runtime_module  # noqa: E402
from main import app  # noqa: E402
from services.model_runtime_manager import ModelRuntimeManager  # noqa: E402
from services.resource_lease import inference_lease  # noqa: E402


class EchoEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": "answer: 42", "usage": {"total_tokens": 7}}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "answer: 42"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _auth(client: TestClient) -> dict:
    username = f"v18{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: EchoEngine(path)),
    )
    try:
        with TestClient(app) as client:
            headers = _auth(client)
            asset = models / "obs.gguf"
            asset.write_bytes(b"GGUF")
            model_id = client.post(
                "/api/v1/models/install",
                json={"name": "obs-model", "provider": "local", "path": str(asset)},
                headers=headers,
            ).json()["id"]
            # Agent names are globally unique (a shared namespace), so each test
            # uses its own name.
            agent_id = f"obs-agent-{uuid.uuid4().hex[:8]}"
            created = client.post(
                "/api/v1/agents",
                json={"name": agent_id, "model_id": model_id},
                headers=headers,
            )
            assert created.status_code == 200, created.text
            yield {"client": client, "headers": headers, "model_id": model_id, "agent_id": agent_id}
    finally:
        holder = inference_lease.holder()
        if holder is not None:
            inference_lease.release(user_id=holder.user_id)


def test_trace_index_and_lookup_across_agent_and_workflow(env):
    client, headers = env["client"], env["headers"]
    run = client.post(
        f"/api/v1/agents/{env['agent_id']}/runs", json={"input": "hello", "confirm": True}, headers=headers
    ).json()
    for _ in range(100):
        status = client.get(f"/api/v1/agents/runs/{run['run_id']}", headers=headers).json()["status"]
        if status in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)

    listing = client.get("/api/v1/traces", params={"kind": "agent"}, headers=headers)
    assert listing.status_code == 200
    traces = listing.json()["traces"]
    assert [item["trace_id"] for item in traces] == [run["run_id"]]
    assert traces[0]["kind"] == "agent"

    fetched = client.get(f"/api/v1/traces/{run['run_id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["summary"]["model_calls"] >= 1

    assert client.get("/api/v1/traces/does-not-exist", headers=headers).status_code == 404


def test_metrics_and_resource_overview(env):
    client, headers = env["client"], env["headers"]
    client.post(
        "/api/v1/chat",
        json={"model": "obs-model", "model_id": env["model_id"], "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )

    metrics = client.get("/api/v1/metrics/overview", headers=headers)
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["ttft_ms"] is None
    assert body["totals"]["requests"] >= 1
    assert "models" in body

    resources = client.get("/api/v1/metrics/resources", headers=headers)
    assert resources.status_code == 200
    payload = resources.json()
    assert "resources" in payload and "instances" in payload and "queue" in payload


def test_evaluation_dataset_run_and_compare(env):
    client, headers = env["client"], env["headers"]

    created = client.post(
        "/api/v1/evaluations",
        json={
            "name": "Smoke",
            "cases": [
                {"name": "math", "input": "2+2?", "expected": "42"},
                {"name": "json", "input": "give json", "expect_json": False},
            ],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    evaluation_id = created.json()["evaluation_id"]

    run = client.post(
        f"/api/v1/evaluations/{evaluation_id}/runs",
        json={"target_kind": "agent", "target_id": env["agent_id"], "timeout_seconds": 10},
        headers=headers,
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "COMPLETED"
    assert body["metrics"]["case_count"] == 2
    assert body["metrics"]["success_rate"] == 1.0, body["results"]
    assert body["metrics"]["accuracy"] == 1.0, body["results"]
    assert len(body["results"]) == 2

    second = client.post(
        f"/api/v1/evaluations/{evaluation_id}/runs",
        json={"target_kind": "agent", "target_id": env["agent_id"], "timeout_seconds": 10},
        headers=headers,
    ).json()
    comparison = client.post(
        "/api/v1/evaluations/compare",
        json={"run_ids": [body["run_id"], second["run_id"]]},
        headers=headers,
    )
    assert comparison.status_code == 200
    assert comparison.json()["deltas"]["success_rate"] == 0.0

    listed = client.get("/api/v1/evaluations/runs", headers=headers).json()["runs"]
    assert len(listed) == 2
    assert client.delete(f"/api/v1/evaluations/{evaluation_id}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/evaluations/{evaluation_id}", headers=headers).status_code == 404


def test_evaluation_validation(env):
    client, headers = env["client"], env["headers"]

    empty = client.post(
        "/api/v1/evaluations", json={"name": "x", "cases": [{"input": "  "}]}, headers=headers
    )
    assert empty.status_code == 400
    assert empty.json()["detail"]["code"] == "EVALUATION_CASE_INVALID"

    assert client.post(
        "/api/v1/evaluations/compare", json={"run_ids": ["a"]}, headers=headers
    ).status_code == 422


def test_secret_backend_reports_state_without_values(env):
    response = env["client"].get("/api/v1/security/secrets", headers=env["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] in {"keychain", "encrypted-file"}
    assert body["fallback"] == "encrypted-provider-column"
    assert "value" not in body
