"""End-to-end HTTP coverage for the model registry + runtime endpoints."""

from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import services.model_runtime_manager as runtime_module  # noqa: E402
from core.config import settings  # noqa: E402
from main import app  # noqa: E402
from services.model_runtime_manager import ModelRuntimeManager  # noqa: E402
from services.resource_lease import inference_lease  # noqa: E402


class FakeEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.stopped = False

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded", "model": model_name}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"model": model_name, "content": "fake reply", "raw": None}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "fake reply"

    async def stop(self, model_name: str) -> dict:
        self.stopped = True
        return {"status": "stopped", "model": model_name}


def _auth(client: TestClient) -> tuple[dict, str]:
    username = f"runtime{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}, username


@pytest.fixture
def api(tmp_path, monkeypatch):
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
    gguf = models / "chat-model.gguf"
    gguf.write_bytes(b"GGUF-placeholder")
    try:
        with TestClient(app) as client:
            headers, username = _auth(client)
            monkeypatch.setattr(settings, "runtime_admin_usernames", username)
            created = client.post(
                "/api/v1/models/install",
                json={"name": "chat-model", "provider": "local", "path": str(gguf)},
                headers=headers,
            )
            assert created.status_code == 200, created.text
            yield {
                "client": client,
                "headers": headers,
                "model_id": created.json()["id"],
                "models": models,
                "username": username,
            }
    finally:
        # The inference lease is process-wide; a failed assertion mid-test must
        # not leak it into the next test's account.
        holder = inference_lease.holder()
        if holder is not None:
            inference_lease.release(user_id=holder.user_id)


def test_list_models_exposes_capabilities_and_runtime_status(api):
    response = api["client"].get("/api/v1/models", headers=api["headers"])

    assert response.status_code == 200
    model = next(item for item in response.json() if item["id"] == api["model_id"])
    assert model["capabilities"] == ["CHAT", "INFERENCE"]
    assert model["ready"] is True
    assert model["runtime_status"] == "idle"
    assert model["model_id"] == model["id"]


def test_capability_filter_selects_the_right_models(api):
    client, headers = api["client"], api["headers"]

    chat = client.get("/api/v1/models", params={"capability": "CHAT"}, headers=headers)
    training = client.get("/api/v1/models", params={"capability": "TRAINING"}, headers=headers)
    invalid = client.get("/api/v1/models", params={"capability": "NOPE"}, headers=headers)

    assert [item["id"] for item in chat.json()] == [api["model_id"]]
    assert training.json() == []
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "MODEL_CAPABILITY_INVALID"


def test_load_status_and_unload_lifecycle(api):
    client, headers, model_id = api["client"], api["headers"], api["model_id"]

    loaded = client.post(f"/api/v1/models/{model_id}/load", json={"context_length": 2048}, headers=headers)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["status"] == "loaded"
    assert loaded.json()["model_id"] == model_id

    status = client.get(f"/api/v1/models/{model_id}/runtime", headers=headers)
    assert status.status_code == 200
    assert status.json()["active"] is True
    assert status.json()["context_length"] == 2048

    instance = client.get("/api/v1/runtime", headers=headers)
    assert instance.status_code == 200
    assert instance.json()["active"] is True

    unloaded = client.post(f"/api/v1/models/{model_id}/unload", headers=headers)
    assert unloaded.status_code == 200
    assert unloaded.json()["unloaded"] is True
    assert client.get(f"/api/v1/models/{model_id}/runtime", headers=headers).json()["active"] is False


def test_load_unknown_model_is_a_stable_problem(api):
    response = api["client"].post("/api/v1/models/999999/load", json={}, headers=api["headers"])

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MODEL_NOT_FOUND"
    assert "details" in response.json()["detail"]


def test_delete_is_blocked_while_the_model_is_loaded(api):
    client, headers, model_id = api["client"], api["headers"], api["model_id"]
    client.post(f"/api/v1/models/{model_id}/load", json={}, headers=headers)

    blocked = client.delete(f"/api/v1/models/{model_id}", headers=headers)

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "MODEL_ALREADY_LOADED"
    client.post(f"/api/v1/models/{model_id}/unload", headers=headers)
    assert client.delete(f"/api/v1/models/{model_id}", headers=headers).status_code == 200


def test_default_model_endpoint_round_trip(api):
    client, headers, model_id = api["client"], api["headers"], api["model_id"]

    assert client.get("/api/v1/models/default", headers=headers).json()["model_id"] is None
    marked = client.post(f"/api/v1/models/{model_id}/default", headers=headers)
    assert marked.status_code == 200, marked.text
    assert client.get("/api/v1/models/default", headers=headers).json()["model_id"] == model_id


def test_default_model_does_not_track_the_loaded_instance(api):
    client, headers, model_id = api["client"], api["headers"], api["model_id"]
    client.post(f"/api/v1/models/{model_id}/default", headers=headers)
    # Loading a model must not silently rewrite the user's default preference.
    other = api["models"] / "other.gguf"
    other.write_bytes(b"GGUF-placeholder")
    other_id = client.post(
        "/api/v1/models/install",
        json={"name": "other-model", "provider": "local", "path": str(other)},
        headers=headers,
    ).json()["id"]
    client.post(f"/api/v1/models/{other_id}/load", json={}, headers=headers)

    assert client.get("/api/v1/models/default", headers=headers).json()["model_id"] == model_id
