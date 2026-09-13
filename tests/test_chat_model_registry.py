"""Chat resolves ``model_id`` through the registry and auto-loads the runtime."""

from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import services.model_runtime_manager as runtime_module  # noqa: E402
from main import app  # noqa: E402
from services.model_runtime_manager import ModelRuntimeManager  # noqa: E402
from services.resource_lease import inference_lease  # noqa: E402


class TaggedEngine:
    """Echoes the model it belongs to so cross-model leakage is observable."""

    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": f"{os.path.basename(self.model_path)}:{messages[-1]['content']}", "raw": None}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield f"{os.path.basename(self.model_path)}:"
        yield messages[-1]["content"]

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _auth(client: TestClient) -> dict:
    username = f"chatreg{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def chat_api(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: TaggedEngine(path)),
    )
    try:
        with TestClient(app) as client:
            headers = _auth(client)
            ids = {}
            for name in ("alpha", "beta"):
                asset = models / f"{name}.gguf"
                asset.write_bytes(b"GGUF-placeholder")
                created = client.post(
                    "/api/v1/models/install",
                    json={"name": name, "provider": "local", "path": str(asset)},
                    headers=headers,
                )
                assert created.status_code == 200, created.text
                ids[name] = created.json()["id"]
            yield {"client": client, "headers": headers, "ids": ids}
    finally:
        holder = inference_lease.holder()
        if holder is not None:
            inference_lease.release(user_id=holder.user_id)


def test_chat_with_model_id_auto_loads_and_replies(chat_api):
    client, headers, ids = chat_api["client"], chat_api["headers"], chat_api["ids"]

    response = client.post(
        "/api/v1/chat",
        json={"model": "alpha", "model_id": ids["alpha"], "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["response"] == "alpha.gguf:hi"
    assert runtime_module.get_model_runtime_manager().get_current().model_id == ids["alpha"]


def test_chat_switch_does_not_reuse_the_previous_model(chat_api):
    client, headers, ids = chat_api["client"], chat_api["headers"], chat_api["ids"]
    payload = lambda name: {"model": name, "model_id": ids[name], "messages": [{"role": "user", "content": "ping"}]}  # noqa: E731

    first = client.post("/api/v1/chat", json=payload("alpha"), headers=headers)
    second = client.post("/api/v1/chat", json=payload("beta"), headers=headers)

    assert first.json()["response"] == "alpha.gguf:ping"
    assert second.json()["response"] == "beta.gguf:ping"
    assert runtime_module.get_model_runtime_manager().get_current().model_id == ids["beta"]


def test_chat_stream_with_model_id(chat_api):
    client, headers, ids = chat_api["client"], chat_api["headers"], chat_api["ids"]

    response = client.post(
        "/api/v1/chat/stream",
        json={"model": "beta", "model_id": ids["beta"], "messages": [{"role": "user", "content": "s"}]},
        headers=headers,
    )

    assert response.status_code == 200
    assert '"type": "delta"' in response.text
    assert "beta.gguf:" in response.text
    assert '"type": "done"' in response.text


def test_chat_unknown_model_id_is_reported(chat_api):
    client, headers = chat_api["client"], chat_api["headers"]

    response = client.post(
        "/api/v1/chat",
        json={"model": "ghost", "model_id": 999999, "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MODEL_NOT_FOUND"


def test_legacy_model_name_chat_still_uses_the_runtime_registry(chat_api, monkeypatch):
    """A model name that is not in the registry keeps the legacy code path."""
    from services.runtime_registry import RuntimeRegistry

    async def fake_chat(self, model, messages, **kwargs):
        return {"model": model, "content": "legacy reply", "raw": None}

    monkeypatch.setattr(RuntimeRegistry, "chat", fake_chat)
    client, headers = chat_api["client"], chat_api["headers"]

    response = client.post(
        "/api/v1/chat",
        json={"model": "some-ollama-tag", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["response"] == "legacy reply"
