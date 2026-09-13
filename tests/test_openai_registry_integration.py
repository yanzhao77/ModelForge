"""The OpenAI-compatible API shares the unified model registry and runtime."""

from __future__ import annotations

import json
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


class FakeEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": f"registry:{messages[-1]['content']}", "raw": None}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "registry"
        yield ":stream"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _auth(client: TestClient) -> dict:
    username = f"oaireg{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def openai_api(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: FakeEngine(path)),
    )
    try:
        with TestClient(app) as client:
            headers = _auth(client)
            asset = models / "openai-model.gguf"
            asset.write_bytes(b"GGUF-placeholder")
            created = client.post(
                "/api/v1/models/install",
                json={"name": "openai-model", "provider": "local", "path": str(asset)},
                headers=headers,
            )
            assert created.status_code == 200, created.text
            yield {"client": client, "headers": headers, "model_id": created.json()["id"]}
    finally:
        holder = inference_lease.holder()
        if holder is not None:
            inference_lease.release(user_id=holder.user_id)


def test_v1_models_lists_registry_models(openai_api):
    response = openai_api["client"].get("/v1/models", headers=openai_api["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    entry = next(item for item in body["data"] if item["id"] == "openai-model")
    assert entry["model_id"] == openai_api["model_id"]
    assert entry["capabilities"] == ["CHAT", "INFERENCE"]


def test_chat_completions_uses_the_registry_runtime(openai_api):
    response = openai_api["client"].post(
        "/v1/chat/completions",
        json={"model": "openai-model", "messages": [{"role": "user", "content": "hi"}]},
        headers=openai_api["headers"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "registry:hi"
    assert runtime_module.get_model_runtime_manager().get_current().model_id == openai_api["model_id"]


def test_chat_completions_streams_from_the_registry_runtime(openai_api):
    response = openai_api["client"].post(
        "/v1/chat/completions",
        json={"model": "openai-model", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        headers=openai_api["headers"],
    )

    assert response.status_code == 200
    assert "registry" in response.text
    assert ":stream" in response.text
    assert "[DONE]" in response.text
    # Deltas must be valid OpenAI-style chunks.
    for line in response.text.splitlines():
        if line.startswith("data: ") and "[DONE]" not in line:
            payload = json.loads(line[6:])
            assert payload["choices"][0]["delta"]["content"]


def test_unknown_model_name_still_uses_the_legacy_runtime(openai_api, monkeypatch):
    from services.runtime_registry import RuntimeRegistry

    class LegacyEngine:
        async def chat(self, model, messages, **kwargs):
            return {"model": model, "content": "legacy openai reply", "raw": None}

    monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: LegacyEngine())
    monkeypatch.setattr(RuntimeRegistry, "chat", LegacyEngine.chat)

    response = openai_api["client"].post(
        "/v1/chat/completions",
        json={"model": "some-unregistered-tag", "messages": [{"role": "user", "content": "hi"}]},
        headers=openai_api["headers"],
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "legacy openai reply"
