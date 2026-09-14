"""V2.0 platform E2E: the six end-to-end chains from the roadmap.

Model / Agent / RAG / Training / Workflow / External API, plus the dashboard and
unified event feed. Heavy inference is replaced by a deterministic fake engine
and the training subprocess by a scripted state file, so every boundary between
registry, runtime, agent, workflow, task center and API is exercised.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import services.model_runtime_manager as runtime_module  # noqa: E402
import services.training as training_module  # noqa: E402
from core.config import settings  # noqa: E402
from main import app  # noqa: E402
from services.model_runtime_manager import ModelRuntimeManager  # noqa: E402
from services.resource_lease import inference_lease, training_lease  # noqa: E402


class PlatformEngine:
    """Answers everything; emits a tool call on the first scripted reply."""

    script: list[str] = []

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.responses = list(type(self).script)

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        content = self.responses.pop(0) if self.responses else "platform answer"
        return {"content": content, "usage": {"total_tokens": 5}}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "platform answer"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _auth(client: TestClient) -> tuple[dict, int]:
    username = f"v20{uuid.uuid4().hex[:10]}"
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


def _local_key(client: TestClient, headers: dict) -> dict:
    issued = client.post("/api/v1/local-api/keys", json={"name": "platform-e2e"}, headers=headers)
    assert issued.status_code == 200, issued.text
    return {"Authorization": "Bearer " + issued.json()["secret"]}


@pytest.fixture
def platform_env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "agent_workspace_root", str(tmp_path / "agent-workspaces"))
    monkeypatch.setattr(settings, "train_output_dir", str(outputs))
    monkeypatch.setattr(training_module, "_torch_available", lambda: True)
    monkeypatch.setattr(training_module.TrainingService, "POLL_INTERVAL", 0.05)
    monkeypatch.setattr(
        training_module.TrainingService,
        "_launch",
        lambda self, cfg, state, log: (
            open(state, "w", encoding="utf-8").write(json.dumps({"status": "done", "progress": 100, "epoch": 1, "loss": 0.1})),
            open(log, "w", encoding="utf-8").write("done\n"),
            MagicMock(poll=lambda: 0, returncode=0, terminate=lambda: None),
        )[-1],
    )
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: PlatformEngine(path)),
    )
    PlatformEngine.script = []
    try:
        with TestClient(app) as client:
            headers, user_id = _auth(client)
            yield {"client": client, "headers": headers, "api_headers": _local_key(client, headers), "user_id": user_id, "models": models}
    finally:
        for lease in (inference_lease, training_lease):
            holder = lease.holder()
            if holder is not None:
                lease.release(user_id=holder.user_id)


def _install_model(client, headers, models, name="platform-model"):
    asset = models / f"{name}.gguf"
    asset.write_bytes(b"GGUF-placeholder")
    return client.post(
        "/api/v1/models/install",
        json={"name": name, "provider": "local", "path": str(asset)},
        headers=headers,
    ).json()["id"]


def test_chain_model_lifecycle(platform_env):
    client, headers, models = platform_env["client"], platform_env["headers"], platform_env["models"]
    model_id = _install_model(client, headers, models)

    listed = client.get("/api/v1/models", params={"capability": "CHAT"}, headers=headers).json()
    assert [item["id"] for item in listed] == [model_id]

    assert client.post(f"/api/v1/models/{model_id}/load", json={}, headers=headers).status_code == 200
    chat = client.post(
        "/api/v1/chat",
        json={"model": "platform-model", "model_id": model_id, "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    assert chat.status_code == 200, chat.text
    assert client.post(f"/api/v1/models/{model_id}/unload", headers=headers).status_code == 200
    assert client.get(f"/api/v1/models/{model_id}/runtime", headers=headers).json()["active"] is False


def test_chain_agent_tool_memory(platform_env):
    from core.agent_file_access import workspace_root_for_user

    client, headers, models, user_id = (
        platform_env["client"], platform_env["headers"], platform_env["models"], platform_env["user_id"]
    )
    model_id = _install_model(client, headers, models, "agent-model")
    PlatformEngine.script = [
        '{"tool_calls": [{"name": "filesystem.read", "arguments": {"filepath": "note.txt"}}]}',
        "final answer",
    ]
    workspace = workspace_root_for_user(user_id)
    (workspace / "note.txt").write_text("remembered context", encoding="utf-8")
    client.post(
        "/api/v1/memories",
        json={"memory_type": "fact", "key": "pref", "value": "prefers Chinese"},
        headers=headers,
    )
    created = client.post(
        "/api/v1/agents",
        json={
            "name": "platform-agent",
            "model_id": model_id,
            "tools": ["filesystem.read"],
            "policy": {"filesystem_access": True},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    run = client.post(
        "/api/v1/agents/platform-agent/runs", json={"input": "read note", "confirm": True}, headers=headers
    ).json()
    status = {}
    for _ in range(100):
        status = client.get(f"/api/v1/agents/runs/{run['run_id']}", headers=headers).json()
        if status["status"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)

    assert status["status"] == "COMPLETED", status
    assert status["output"] == "final answer"
    trace = client.get(f"/api/v1/agents/runs/{run['run_id']}/trace", headers=headers).json()
    assert trace["summary"]["tool_calls"] >= 1
    assert any(span["type"] == "memory" for span in trace["spans"]) or trace["summary"]["model_calls"] >= 2


def test_chain_rag_document_to_answer(platform_env):
    client, headers, api_headers = platform_env["client"], platform_env["headers"], platform_env["api_headers"]
    client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("rag.md", b"ModelForge unifies model lifecycle and runtime.", "text/markdown")},
        headers=headers,
    )
    base = client.post("/api/v1/knowledge/bases", json={"name": "Docs"}, headers=headers).json()
    documents = client.get(f"/api/v1/knowledge/bases/{base['knowledge_id']}/documents", headers=headers).json()

    query = client.post(
        "/api/v1/knowledge/query",
        json={
            "question": "model lifecycle runtime",
            "top_k": 3,
            "retrieval_mode": "hybrid",
            "knowledge_binding": {"mode": "all"},
        },
        headers=headers,
    )
    assert query.status_code == 200, query.text
    assert query.json()["results"]
    assert query.json()["retrieval_mode"] == "hybrid"
    assert documents["documents"] == []  # uploaded without a knowledge_id

    search = client.post(
        "/v1/knowledge/search",
        json={"query": "model lifecycle", "top_k": 2, "knowledge_id": base["knowledge_id"]},
        headers=api_headers,
    )
    assert search.status_code == 200
    # The document was not attached to the base, so a collection-scoped search is empty.
    assert search.json()["data"] == []


def test_chain_training_artifact_back_to_chat(platform_env):
    client, headers, models = platform_env["client"], platform_env["headers"], platform_env["models"]
    base_dir = models / "hf-base"
    base_dir.mkdir()
    (base_dir / "config.json").write_text('{"model_type": "llama"}', encoding="utf-8")
    (base_dir / "model.safetensors").write_bytes(b"weights")
    base = client.post(
        "/api/v1/models/install",
        json={"name": "hf-base", "provider": "local", "path": str(base_dir)},
        headers=headers,
    ).json()
    dataset = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("t.jsonl", b'{"text": "hello"}\n' * 3, "application/json")},
        headers=headers,
    ).json()
    started = client.post(
        "/api/v1/train/start",
        json={
            "dataset_id": dataset["id"],
            "base_model_id": base["id"],
            "method": "full",
            "epochs": 1,
            "batch_size": 1,
            "confirm": True,
        },
        headers=headers,
    )
    assert started.status_code == 200, started.text
    task_id = started.json()["task_id"]
    status = {}
    for _ in range(100):
        status = client.get(f"/api/v1/train/status/{task_id}", headers=headers).json()
        if status["status"] == "done":
            break
        time.sleep(0.05)
    assert status["status"] == "done", status
    output = status["output_dir"]
    with open(os.path.join(output, "config.json"), "w", encoding="utf-8") as handle:
        handle.write('{"model_type": "llama"}')
    with open(os.path.join(output, "model.safetensors"), "wb") as handle:
        handle.write(b"weights")

    registered = client.post(
        f"/api/v1/train/{task_id}/register-model", json={"confirm": True}, headers=headers
    )
    assert registered.status_code == 200, registered.text
    artifact = registered.json()
    assert artifact["capabilities"] == ["CHAT", "INFERENCE"]

    assert client.post(f"/api/v1/models/{artifact['id']}/load", json={}, headers=headers).status_code == 200
    chat = client.post(
        "/api/v1/chat",
        json={"model": artifact["name"], "model_id": artifact["id"], "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    assert chat.status_code == 200, chat.text


def test_chain_workflow_and_external_api(platform_env):
    client, headers, api_headers, models = platform_env["client"], platform_env["headers"], platform_env["api_headers"], platform_env["models"]
    _install_model(client, headers, models, "wf-model")
    definition = {
        "entry": "start",
        "nodes": [
            {"id": "start", "type": "input", "next": "plan"},
            {"id": "plan", "type": "llm", "config": {"prompt": "plan: {{input.question}}"}, "next": "fan"},
            {"id": "fan", "type": "parallel", "branches": [["research"], ["draft"]], "next": "review"},
            {"id": "research", "type": "llm", "config": {"prompt": "research"}},
            {"id": "draft", "type": "llm", "config": {"prompt": "draft"}},
            {
                "id": "review",
                "type": "condition",
                "config": {"expression": "'[echo]' in nodes.draft.output"},
                "true_next": "publish",
                "false_next": "draft",
            },
            {"id": "publish", "type": "output", "config": {"value": "{{nodes.draft.output}}"}},
        ],
    }
    workflow = client.post("/api/v1/workflows", json={"name": "Pipeline", "definition": definition}, headers=headers).json()
    run = client.post(
        f"/api/v1/workflows/{workflow['workflow_id']}/runs",
        json={"input": {"question": "go"}, "confirm": True},
        headers=headers,
    ).json()
    status = {}
    for _ in range(100):
        status = client.get(f"/api/v1/workflows/runs/{run['run_id']}", headers=headers).json()
        if status["status"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)
    assert status["status"] == "COMPLETED", status

    # External API chain: /v1/models -> /v1/chat/completions -> runtime.
    models_list = client.get("/v1/models", headers=api_headers)
    assert models_list.status_code == 200
    assert any(item["id"] == "wf-model" for item in models_list.json()["data"])
    chat = client.post(
        "/v1/chat/completions",
        json={"model": "wf-model", "messages": [{"role": "user", "content": "hi"}]},
        headers=api_headers,
    )
    assert chat.status_code == 200, chat.text
    assert chat.json()["choices"][0]["message"]["content"] == "platform answer"

    # Dashboard + unified events aggregate the whole platform.
    dashboard = client.get("/api/v1/dashboard", headers=headers)
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["system"]["ready_models"] >= 1
    assert body["runtime"]["max_instances"] >= 1
    assert any(item["workflow_id"] == workflow["workflow_id"] for item in body["workflows"])

    events = client.get("/api/v1/events", headers=headers).json()
    kinds = {event["kind"] for event in events["events"]}
    assert "workflow" in kinds
