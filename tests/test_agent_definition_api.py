"""V1.1 AgentDefinition API, model_id binding, Run and Trace."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import services.model_runtime_manager as runtime_module  # noqa: E402
from core.config import settings  # noqa: E402
from main import app  # noqa: E402
from runtime.tools.base import PermissionLevel  # noqa: E402
from services.model_runtime_manager import ModelRuntimeManager  # noqa: E402
from services.resource_lease import inference_lease  # noqa: E402


class ScriptedEngine:
    """Returns a tool call first, then a final answer."""

    script: list[str] = []

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.responses = list(type(self).script)

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        content = self.responses.pop(0) if self.responses else "all done"
        return {"content": content, "raw": None}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "streamed"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _auth(client: TestClient) -> tuple[dict, int]:
    username = f"v11{uuid.uuid4().hex[:10]}"
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "agent_workspace_root", str(tmp_path / "agent-workspaces"))
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: ScriptedEngine(path)),
    )
    ScriptedEngine.script = [
        '{"tool_calls": [{"name": "filesystem.read", "arguments": {"filepath": "hostname.txt"}}]}',
        "final answer",
    ]
    try:
        with TestClient(app) as client:
            headers, user_id = _auth(client)
            asset = models / "agent-model.gguf"
            asset.write_bytes(b"GGUF-placeholder")
            created = client.post(
                "/api/v1/models/install",
                json={"name": "agent-model", "provider": "local", "path": str(asset)},
                headers=headers,
            )
            assert created.status_code == 200, created.text
            yield {
                "client": client,
                "headers": headers,
                "user_id": user_id,
                "model_id": created.json()["id"],
                "tmp_path": tmp_path,
            }
    finally:
        for lease in (inference_lease,):
            holder = lease.holder()
            if holder is not None:
                lease.release(user_id=holder.user_id)


def test_agent_definition_crud_is_bound_to_model_id(env):
    client, headers, model_id = env["client"], env["headers"], env["model_id"]

    created = client.post(
        "/api/v1/agents",
        json={
            "name": "writer",
            "description": "writes things",
            "model_id": model_id,
            "system_prompt": "be concise",
            "tools": ["filesystem.read"],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    agent = created.json()
    assert agent["model_id"] == model_id
    assert agent["model"] == "agent-model"
    assert agent["definition"]["model_id"] == model_id

    listed = client.get("/api/v1/agents", headers=headers).json()["agents"]
    assert [item["name"] for item in listed] == ["writer"]

    detail = client.get("/api/v1/agents/writer", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["model_id"] == model_id

    updated = client.put(
        "/api/v1/agents/writer",
        json={"description": "updated", "tools": ["filesystem.read", "knowledge.search"]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "updated"
    assert set(updated.json()["tools"]) == {"filesystem.read", "knowledge.search"}

    versions = client.get("/api/v1/agents/writer/versions", headers=headers).json()["versions"]
    assert len(versions) >= 2

    assert client.delete("/api/v1/agents/writer", headers=headers).status_code == 200
    assert client.get("/api/v1/agents/writer", headers=headers).status_code == 404


def test_agent_definition_rejects_unknown_model(env):
    response = env["client"].post(
        "/api/v1/agents",
        json={"name": "ghost-agent", "model_id": 999999},
        headers=env["headers"],
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MODEL_NOT_FOUND"


def test_agent_definitions_are_user_scoped(env):
    client = env["client"]
    client.post("/api/v1/agents", json={"name": "private-agent", "model_id": env["model_id"]}, headers=env["headers"])
    other_headers, _ = _auth(client)

    assert client.get("/api/v1/agents/private-agent", headers=other_headers).status_code == 404
    assert [item["name"] for item in client.get("/api/v1/agents", headers=other_headers).json()["agents"]] == []


def test_agent_run_produces_a_complete_trace(env):
    from core.agent_file_access import workspace_root_for_user

    client, headers, model_id, user_id = env["client"], env["headers"], env["model_id"], env["user_id"]
    workspace = workspace_root_for_user(user_id)
    (workspace / "hostname.txt").write_text("safe host label", encoding="utf-8")
    created = client.post(
        "/api/v1/agents",
        json={
            "name": "tracer",
            "model_id": model_id,
            "tools": ["filesystem.read"],
            "policy": {"filesystem_access": True},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    run = client.post("/api/v1/agents/tracer/runs", json={"input": "read the file", "confirm": True}, headers=headers)
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]

    status = {}
    for _ in range(100):
        status = client.get(f"/api/v1/agents/runs/{run_id}", headers=headers).json()
        if status["status"] in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}:
            break
        time.sleep(0.05)
    assert status["status"] == "COMPLETED", status
    assert status["output"] == "final answer"
    assert status["tool_call_count"] >= 1

    trace = client.get(f"/api/v1/agents/runs/{run_id}/trace", headers=headers)
    assert trace.status_code == 200, trace.text
    document = trace.json()
    assert document["trace_id"] == run_id
    assert document["status"] == "COMPLETED"
    assert document["summary"]["model_calls"] >= 2  # tool round-trip + final
    assert document["summary"]["tool_calls"] >= 1
    assert any(span["type"] == "tool" for span in document["spans"])
    assert any(span["type"] == "run" for span in document["spans"])
    assert document["events"], "trace must keep the raw event stream"
    # No absolute workspace path is echoed in the trace summary.
    assert str(env["tmp_path"]) not in json.dumps(document["summary"])


def test_agent_run_trace_is_user_scoped(env):
    client = env["client"]
    client.post("/api/v1/agents", json={"name": "owner-agent", "model_id": env["model_id"]}, headers=env["headers"])
    run = client.post(
        "/api/v1/agents/owner-agent/runs", json={"input": "hi", "confirm": True}, headers=env["headers"]
    ).json()
    other_headers, _ = _auth(client)

    assert client.get(f"/api/v1/agents/runs/{run['run_id']}/trace", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/agents/runs/{run['run_id']}", headers=other_headers).status_code == 404


def test_permission_catalog_maps_roadmap_names():
    catalog = PermissionLevel.catalog()

    assert catalog["READ_ONLY"] == PermissionLevel.READ
    assert catalog["FILESYSTEM_WRITE"] == PermissionLevel.WRITE
    assert catalog["PROCESS_EXECUTE"] == PermissionLevel.EXECUTE
    assert catalog["DANGEROUS"] == PermissionLevel.SYSTEM
    assert PermissionLevel.normalize(["READ_ONLY", "PROCESS_EXECUTE"]) == [
        PermissionLevel.READ,
        PermissionLevel.EXECUTE,
    ]


def test_tool_call_parser_round_trip():
    from services.tool_call_parser import parse_tool_calls

    content, calls = parse_tool_calls(
        'Thinking...\n```json\n{"tool_calls": [{"name": "shell.execute", "arguments": {"command": "ls"}}]}\n```'
    )

    assert content == "Thinking..."
    assert calls == [{"id": calls[0]["id"], "name": "shell.execute", "arguments": {"command": "ls"}}]

    plain, none = parse_tool_calls("just an answer")
    assert plain == "just an answer"
    assert none == []
