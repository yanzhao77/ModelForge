"""V1.7 Package export/import for workflow, agent, model and tool packages."""

from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402

SEQUENTIAL = {
    "entry": "start",
    "nodes": [
        {"id": "start", "type": "input", "next": "ask"},
        {"id": "ask", "type": "llm", "config": {"prompt": "{{input.question}}"}, "next": "done"},
        {"id": "done", "type": "output", "config": {"value": "{{nodes.ask.output}}"}},
    ],
}


def _auth(client: TestClient) -> dict:
    username = f"v17{uuid.uuid4().hex[:10]}"
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
    with TestClient(app) as client:
        yield {"client": client, "headers": _auth(client), "models": models}


def test_workflow_package_round_trip(env):
    client, headers = env["client"], env["headers"]
    workflow = client.post(
        "/api/v1/workflows", json={"name": "Packaged", "definition": SEQUENTIAL}, headers=headers
    ).json()

    exported = client.post(
        "/api/v1/packages/export",
        json={"kind": "workflow", "ref": workflow["workflow_id"], "version": "1.2.0", "license": "MIT"},
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    document = exported.json()
    assert document["manifest"]["kind"] == "workflow"
    assert document["manifest"]["version"] == "1.2.0"
    assert document["manifest"]["license"] == "MIT"
    assert document["manifest"]["package_id"].startswith("workflow:")
    assert document["payload"]["definition"]["entry"] == "start"

    other = _auth(client)
    imported = client.post("/api/v1/packages/import", json={"document": document}, headers=other)
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["imported"]["name"] == "Packaged-imported"
    assert body["missing_dependencies"] == []

    listed = client.get("/api/v1/packages", headers=other).json()
    assert any(item["kind"] == "workflow" for item in listed["packages"])

    created = client.get(f"/api/v1/workflows/{body['imported']['workflow_id']}", headers=other)
    assert created.status_code == 200
    assert created.json()["name"] == "Packaged-imported"

    detail = client.get(f"/api/v1/packages/{document['manifest']['package_id']}", headers=other)
    assert detail.status_code == 200
    assert detail.json()["versions"] == ["1.2.0"]


def test_model_package_carries_metadata_not_weights(env):
    client, headers = env["client"], env["headers"]
    asset = env["models"] / "pkg.gguf"
    asset.write_bytes(b"GGUF-placeholder")
    model = client.post(
        "/api/v1/models/install",
        json={"name": "pkg-model", "provider": "local", "path": str(asset)},
        headers=headers,
    ).json()

    exported = client.post(
        "/api/v1/packages/export", json={"kind": "model", "ref": str(model["id"])}, headers=headers
    ).json()
    manifest = exported["manifest"]
    assert "llama_cpp" in {item["ref"] for item in manifest["requires"]}
    assert manifest["capabilities"] == ["CHAT", "INFERENCE"]
    assert manifest["format"] == "gguf"
    payload = exported["payload"]
    assert payload["artifact"]["import"] == "download-required"
    # No host path and no weights leave the server.
    serialized = str(exported)
    assert str(env["models"]) not in serialized
    assert "GGUF-placeholder" not in serialized

    imported = client.post("/api/v1/packages/import", json={"document": exported}, headers=headers).json()
    assert imported["imported"]["action_required"] == "download"
    assert imported["imported"]["model_id"] is None


def test_tool_and_agent_packages(env):
    client, headers = env["client"], env["headers"]
    tool = client.post(
        "/api/v1/packages/export", json={"kind": "tool", "ref": "filesystem.read"}, headers=headers
    ).json()
    assert tool["manifest"]["kind"] == "tool"
    assert tool["manifest"]["permissions"] == ["FILESYSTEM_READ"]
    assert tool["payload"]["schema"]["function"]["name"] == "filesystem.read"

    model_id = client.post(
        "/api/v1/models/install",
        json={"name": "agent-model", "provider": "local", "path": str(env["models"] / "a.gguf")},
        headers=headers,
    ).json()["id"]
    (env["models"] / "a.gguf").write_bytes(b"GGUF")
    client.post(
        "/api/v1/agents",
        json={"name": "packaged-agent", "model_id": model_id, "tools": ["filesystem.read"]},
        headers=headers,
    )
    agent = client.post(
        "/api/v1/packages/export", json={"kind": "agent", "ref": "packaged-agent"}, headers=headers
    ).json()
    assert {item["kind"] for item in agent["manifest"]["requires"]} == {"model", "tool"}

    imported = client.post("/api/v1/packages/import", json={"document": agent}, headers=headers).json()
    assert imported["imported"]["agent_id"] == "packaged-agent-imported"
    assert imported["imported"]["model_id"] == model_id


def test_package_errors(env):
    client, headers = env["client"], env["headers"]

    unsupported = client.post(
        "/api/v1/packages/export", json={"kind": "dataset", "ref": "x"}, headers=headers
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"]["code"] == "PACKAGE_KIND_UNSUPPORTED"

    missing = client.post(
        "/api/v1/packages/export", json={"kind": "workflow", "ref": "nope"}, headers=headers
    )
    assert missing.status_code == 404

    invalid = client.post(
        "/api/v1/packages/import", json={"document": {"manifest": {}, "payload": {}}}, headers=headers
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "PACKAGE_KIND_UNSUPPORTED"

    assert client.get("/api/v1/packages/nope", headers=headers).status_code == 404


def test_import_reports_missing_dependencies(env):
    client, headers = env["client"], env["headers"]
    document = {
        "schema_version": 1,
        "manifest": {
            "kind": "workflow",
            "package_id": "workflow:demo",
            "name": "Needs deps",
            "version": "1.0.0",
            "requires": [
                {"kind": "model", "ref": "424242"},
                {"kind": "runtime", "ref": "not-a-runtime"},
            ],
        },
        "payload": {"definition": SEQUENTIAL},
    }

    imported = client.post("/api/v1/packages/import", json={"document": document}, headers=headers).json()

    reasons = {item["reason"] for item in imported["missing_dependencies"]}
    assert reasons == {"MODEL_NOT_REGISTERED", "RUNTIME_UNAVAILABLE"}
