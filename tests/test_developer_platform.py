"""V1.6 Developer Platform: OpenAI-compatible extensions + Python SDK."""

from __future__ import annotations

import os
import sys
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend", "app"))
sys.path.insert(0, os.path.join(ROOT, "sdk", "python"))

import services.model_runtime_manager as runtime_module  # noqa: E402
from main import app  # noqa: E402
from modelforge import ModelForge, ModelForgeError  # noqa: E402
from services.model_runtime_manager import ModelRuntimeManager  # noqa: E402
from services.resource_lease import inference_lease  # noqa: E402


class EchoEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": "sdk answer"}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "sdk answer"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _auth(client: TestClient) -> dict:
    username = f"v16{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _local_key(client: TestClient, headers: dict) -> dict:
    issued = client.post("/api/v1/local-api/keys", json={"name": "developer-platform"}, headers=headers)
    assert issued.status_code == 200, issued.text
    return {"Authorization": "Bearer " + issued.json()["secret"]}


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
            api_headers = _local_key(client, headers)
            asset = models / "sdk.gguf"
            asset.write_bytes(b"GGUF-placeholder")
            client.post(
                "/api/v1/models/install",
                json={"name": "sdk-model", "provider": "local", "path": str(asset)},
                headers=headers,
            )
            yield {"client": client, "headers": headers, "api_headers": api_headers}
    finally:
        holder = inference_lease.holder()
        if holder is not None:
            inference_lease.release(user_id=holder.user_id)


def test_v1_embeddings_matches_openai_shape(env):
    response = env["client"].post(
        "/v1/embeddings", json={"input": ["hello", "world"]}, headers=env["api_headers"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["object"] == "list"
    assert [item["index"] for item in body["data"]] == [0, 1]
    assert len(body["data"][0]["embedding"]) == 256
    assert body["usage"]["total_tokens"] > 0
    assert body["embedding"]["provider"] == "hash"


def test_v1_agent_run_and_trace(env):
    client, headers, api_headers = env["client"], env["headers"], env["api_headers"]
    created = client.post(
        "/api/v1/agents", json={"name": "sdk-agent", "model": "sdk-model"}, headers=headers
    )
    assert created.status_code == 200, created.text
    model_id = created.json()["model_id"]
    assert model_id  # a bare model name still resolves through the registry

    listed = client.get("/v1/agents", headers=api_headers)
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()["data"]] == ["sdk-agent"]

    run = client.post("/v1/agents/sdk-agent/runs", json={"input": "hello"}, headers=api_headers)
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]
    status = {}
    for _ in range(100):
        status = client.get(f"/v1/agents/runs/{run_id}", headers=api_headers).json()
        if status["status"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)
    assert status["status"] == "COMPLETED", status
    trace = client.get(f"/v1/agents/runs/{run_id}/trace", headers=api_headers).json()
    assert trace["summary"]["model_calls"] >= 1


def test_v1_knowledge_search_and_workflow_run(env):
    client, headers, api_headers = env["client"], env["headers"], env["api_headers"]
    client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("sdk.md", b"ModelForge exposes an OpenAI compatible API.", "text/markdown")},
        headers=headers,
    )

    search = client.post(
        "/v1/knowledge/search", json={"query": "OpenAI compatible API", "top_k": 2}, headers=api_headers
    )
    assert search.status_code == 200, search.text
    assert search.json()["data"]
    assert search.json()["retrieval_mode"] == "semantic"

    definition = {
        "entry": "start",
        "nodes": [
            {"id": "start", "type": "input", "next": "ask"},
            {"id": "ask", "type": "llm", "config": {"prompt": "{{input.question}}"}, "next": "done"},
            {"id": "done", "type": "output", "config": {"value": "{{nodes.ask.output}}"}},
        ],
    }
    workflow = client.post(
        "/api/v1/workflows", json={"name": "SDK workflow", "definition": definition}, headers=headers
    ).json()
    run = client.post(
        f"/v1/workflows/{workflow['workflow_id']}/runs",
        json={"input": {"question": "hi"}},
        headers=api_headers,
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]
    status = {}
    for _ in range(100):
        status = client.get(f"/v1/workflows/runs/{run_id}", headers=api_headers).json()
        if status["status"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)
    assert status["status"] == "COMPLETED", status
    assert status["output"] == "[echo] hi"
    trace = client.get(f"/v1/workflows/runs/{run_id}/trace", headers=api_headers).json()
    assert trace["summary"]["node_count"] >= 3


def test_v1_capabilities_catalog(env):
    response = env["client"].get("/v1/platform/capabilities", headers=env["api_headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["endpoints"]["embeddings"] == "/v1/embeddings"
    assert {item["id"] for item in body["runtimes"]} >= {"llama_cpp", "transformers", "remote_openai"}
    assert "approval" in body["workflow_node_types"]
    assert body["tool_permissions"]["PROCESS_EXECUTE"] == "EXECUTE"


# ---------------- Python SDK ----------------


def _sdk_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/login":
            return httpx.Response(200, json={"token": "test-token", "user": {"username": "alice"}})
        if path == "/api/v1/models":
            assert request.headers.get("Authorization") == "Bearer test-token"
            return httpx.Response(200, json=[{"id": 3, "name": "sdk-model", "capabilities": ["CHAT"]}])
        if path == "/api/v1/models/3/load":
            return httpx.Response(200, json={"model_id": 3, "status": "loaded"})
        if path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
        if path == "/v1/embeddings":
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        if path == "/v1/agents/writer/runs":
            return httpx.Response(200, json={"run_id": "run-1", "status": "PENDING"})
        if path == "/v1/agents/runs/run-1":
            return httpx.Response(200, json={"run_id": "run-1", "status": "COMPLETED", "output": "done"})
        if path == "/v1/knowledge/search":
            return httpx.Response(200, json={"data": [{"text": "hit"}], "retrieval_mode": "hybrid"})
        if path == "/v1/workflows/wf-1/runs":
            return httpx.Response(200, json={"run_id": "wrun-1", "status": "PENDING"})
        if path == "/v1/workflows/runs/wrun-1":
            return httpx.Response(200, json={"run_id": "wrun-1", "status": "COMPLETED", "output": "ok"})
        if path == "/api/v1/models/9/load":
            return httpx.Response(
                404,
                json={
                    "detail": {
                        "code": "MODEL_NOT_FOUND",
                        "message": "模型不存在",
                        "correlation_id": "corr-1",
                    }
                },
            )
        return httpx.Response(404, json={"detail": {"code": "NOT_FOUND", "message": path}})

    return httpx.MockTransport(handler)


def test_sdk_round_trips_the_platform_api():
    client = ModelForge("http://modelforge.test", transport=_sdk_transport())
    client.login("alice", "secret123")

    models = client.models.list(capability="CHAT")
    assert models[0]["name"] == "sdk-model"
    assert client.models.load(3)["status"] == "loaded"
    assert client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])["choices"][0]["message"]["content"] == "hi"
    assert client.embeddings.create(["a"])["data"][0]["embedding"] == [0.1, 0.2]
    assert client.knowledge.search("q", retrieval_mode="hybrid")["retrieval_mode"] == "hybrid"

    agent_run = client.agents.run("writer", "hello", wait=True, timeout=5)
    assert agent_run["status"] == "COMPLETED"
    workflow_run = client.workflows.run("wf-1", {"question": "hi"}, wait=True, timeout=5)
    assert workflow_run["output"] == "ok"


def test_sdk_maps_stable_error_codes():
    client = ModelForge("http://modelforge.test", api_key="test-token", transport=_sdk_transport())

    with pytest.raises(ModelForgeError) as excinfo:
        client.models.load(9)

    assert excinfo.value.status == 404
    assert excinfo.value.code == "MODEL_NOT_FOUND"
    assert excinfo.value.correlation_id == "corr-1"
