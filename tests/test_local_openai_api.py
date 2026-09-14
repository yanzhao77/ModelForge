"""Local OpenAI-compatible API key auth and model descriptor tests."""
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


class EchoEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": f"local:{messages[-1]['content']}"}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "local"
        yield ":stream"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _jwt(client: TestClient, prefix: str) -> dict:
    username = f"{prefix}-{uuid.uuid4().hex[:10]}"
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    assert registered.status_code in {200, 201}, registered.text
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["token"]}


def _api_key(client: TestClient, jwt_headers: dict, scopes: list[str] | None = None) -> dict:
    payload = {"name": "pytest"}
    if scopes is not None:
        payload["scopes"] = scopes
    created = client.post("/api/v1/local-api/keys", json=payload, headers=jwt_headers)
    assert created.status_code == 200, created.text
    secret = created.json()["secret"]
    assert secret.startswith("mf-")
    return {"Authorization": "Bearer " + secret}


@pytest.fixture
def local_api_env(tmp_path, monkeypatch):
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
            jwt_headers = _jwt(client, "localapi")
            api_headers = _api_key(client, jwt_headers)
            asset = models / "api-model.gguf"
            asset.write_bytes(b"GGUF-placeholder")
            created = client.post(
                "/api/v1/models/install",
                json={"name": "api-model", "provider": "local", "path": str(asset)},
                headers=jwt_headers,
            )
            assert created.status_code == 200, created.text
            model_id = created.json()["id"]
            yield {"client": client, "jwt": jwt_headers, "api": api_headers, "model_id": model_id}
    finally:
        holder = inference_lease.holder()
        if holder is not None:
            inference_lease.release(user_id=holder.user_id)


def test_v1_rejects_missing_jwt_and_bad_keys(local_api_env):
    client = local_api_env["client"]
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers=local_api_env["jwt"]).status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer mf-bad-key"}).status_code == 401


def test_local_api_key_can_list_model_detail_and_alias(local_api_env):
    client, api, jwt_headers = local_api_env["client"], local_api_env["api"], local_api_env["jwt"]
    model_id = local_api_env["model_id"]

    alias = client.put(f"/api/v1/local-api/models/{model_id}/alias", json={"alias": "chat-primary"}, headers=jwt_headers)
    assert alias.status_code == 200, alias.text

    listed = client.get("/v1/models", headers=api)
    assert listed.status_code == 200, listed.text
    entry = next(item for item in listed.json()["data"] if item["model_id"] == model_id)
    assert entry["id"] == "chat-primary"
    assert entry["compatibility"]["downloadable"] is True
    assert "/v1/chat/completions" in entry["endpoints"]

    detail = client.get("/v1/models/chat-primary", headers=api)
    assert detail.status_code == 200
    assert detail.json()["model_id"] == model_id


def test_chat_and_responses_use_local_api_key_and_log_without_prompt(local_api_env):
    client, api = local_api_env["client"], local_api_env["api"]
    chat = client.post(
        "/v1/chat/completions",
        json={"model": "api-model", "messages": [{"role": "user", "content": "secret prompt"}]},
        headers=api,
    )
    assert chat.status_code == 200, chat.text
    assert chat.json()["choices"][0]["message"]["content"] == "local:secret prompt"

    response = client.post("/v1/responses", json={"model": "api-model", "input": "hello"}, headers=api)
    assert response.status_code == 200, response.text
    assert response.json()["output_text"] == "local:hello"

    logs = client.get("/api/v1/local-api/logs", headers=local_api_env["jwt"]).json()["logs"]
    assert any(item["endpoint"] == "/v1/chat/completions" for item in logs)
    assert "secret prompt" not in str(logs)
    assert "mf-" in logs[0]["key_prefix"]


def test_embedding_model_capability_mismatch_is_clear(local_api_env):
    response = local_api_env["client"].post(
        "/v1/embeddings",
        json={"model": "api-model", "input": ["hello"]},
        headers=local_api_env["api"],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_CAPABILITY_UNSUPPORTED"


def test_image_input_requires_vision_capability(local_api_env):
    response = local_api_env["client"].post(
        "/v1/chat/completions",
        json={
            "model": "api-model",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
                    ],
                }
            ],
        },
        headers=local_api_env["api"],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_CAPABILITY_UNSUPPORTED"


def test_revoked_key_stops_work(local_api_env):
    client, jwt_headers = local_api_env["client"], local_api_env["jwt"]
    keys = client.get("/api/v1/local-api/keys", headers=jwt_headers).json()["keys"]
    revoked = client.post(f"/api/v1/local-api/keys/{keys[0]['id']}/revoke", headers=jwt_headers)
    assert revoked.status_code == 200
    blocked = client.get("/v1/models", headers=local_api_env["api"])
    assert blocked.status_code == 401
    assert blocked.json()["error"]["code"] == "API_KEY_REVOKED"


def test_scope_limited_key_is_rejected(local_api_env):
    client, jwt_headers = local_api_env["client"], local_api_env["jwt"]
    models_only = _api_key(client, jwt_headers, scopes=["models:read"])
    response = client.post(
        "/v1/chat/completions",
        json={"model": "api-model", "messages": [{"role": "user", "content": "hello"}]},
        headers=models_only,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_KEY_SCOPE_DENIED"


def test_disabled_local_api_rejects_v1_requests(local_api_env):
    client, jwt_headers = local_api_env["client"], local_api_env["jwt"]
    stopped = client.post("/api/v1/local-api/stop", headers=jwt_headers)
    assert stopped.status_code == 200, stopped.text
    blocked = client.get("/v1/models", headers=local_api_env["api"])
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "LOCAL_API_DISABLED"
    client.post("/api/v1/local-api/start", headers=jwt_headers)


def test_auto_load_disabled_requires_loaded_model(local_api_env):
    client, jwt_headers = local_api_env["client"], local_api_env["jwt"]
    updated = client.put("/api/v1/local-api/settings", json={"auto_load_models": False}, headers=jwt_headers)
    assert updated.status_code == 200, updated.text
    response = client.post(
        "/v1/chat/completions",
        json={"model": "api-model", "messages": [{"role": "user", "content": "hello"}]},
        headers=local_api_env["api"],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_NOT_LOADED"


def test_request_log_does_not_store_full_key(local_api_env):
    client, api, jwt_headers = local_api_env["client"], local_api_env["api"], local_api_env["jwt"]
    client.get("/v1/models", headers=api)
    secret = api["Authorization"].removeprefix("Bearer ")
    logs = client.get("/api/v1/local-api/logs", headers=jwt_headers).json()["logs"]
    assert secret not in str(logs)
    assert all("Authorization" not in str(item) for item in logs)


def test_chat_and_responses_streaming_sse(local_api_env):
    client, api = local_api_env["client"], local_api_env["api"]
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "api-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
        headers=api,
    ) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "local" in body
    assert "data: [DONE]" in body

    with client.stream(
        "POST",
        "/v1/responses",
        json={"model": "api-model", "input": "hello", "stream": True},
        headers=api,
    ) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "response.output_text.delta" in body
    assert "data: [DONE]" in body
