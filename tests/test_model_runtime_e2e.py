"""End-to-end acceptance for the unified model lifecycle.

Chain under test (task plan phase 11):

    download/install -> registry -> runtime load -> chat
                              |
                        training (base_model_id)
                              |
                         artifact -> registry -> load -> chat

The heavy inference stack is replaced by a deterministic fake engine and the
training subprocess by a scripted state file, so the test exercises every
boundary (registry, runtime manager, API contract) without a GPU.
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


class EchoEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": f"reply:{messages[-1]['content']}", "raw": None}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield f"reply:{messages[-1]['content']}"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


def _auth(client: TestClient) -> dict:
    username = f"e2e{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def environment(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "train_output_dir", str(outputs))
    monkeypatch.setattr(training_module, "_torch_available", lambda: True)
    monkeypatch.setattr(training_module.TrainingService, "POLL_INTERVAL", 0.05)

    def fake_launch(self, cfg_path, state_path, log_path):
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump({"status": "done", "progress": 100, "epoch": 1, "loss": 0.25}, handle)
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("fake training completed\n")
        return MagicMock(poll=lambda: 0, returncode=0, terminate=lambda: None)

    monkeypatch.setattr(training_module.TrainingService, "_launch", fake_launch)
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: EchoEngine(path)),
    )
    yield {"models": models, "outputs": outputs}
    for lease in (inference_lease, training_lease):
        holder = lease.holder()
        if holder is not None:
            lease.release(user_id=holder.user_id)


def test_full_model_lifecycle_from_download_to_training_artifact(environment):
    with TestClient(app) as client:
        headers = _auth(client)

        # 1. A completed download lands in the registry as a chat model.
        chat_asset = environment["models"] / "Qwen_Qwen2.5-0.5B-GGUF" / "qwen2.5-0.5b.Q4_K_M.gguf"
        chat_asset.parent.mkdir(parents=True, exist_ok=True)
        chat_asset.write_bytes(b"GGUF-placeholder")
        installed = client.post(
            "/api/v1/models/install",
            json={"name": "qwen2.5-0.5b", "provider": "download", "path": str(chat_asset)},
            headers=headers,
        )
        assert installed.status_code == 200, installed.text
        chat_model_id = installed.json()["id"]

        chat_models = client.get("/api/v1/models", params={"capability": "CHAT"}, headers=headers).json()
        assert [item["id"] for item in chat_models] == [chat_model_id]
        assert chat_models[0]["capabilities"] == ["CHAT", "INFERENCE"]

        # 2. Load it through the runtime manager and chat by model_id.
        loaded = client.post(f"/api/v1/models/{chat_model_id}/load", json={}, headers=headers)
        assert loaded.status_code == 200, loaded.text
        reply = client.post(
            "/api/v1/chat",
            json={"model": "qwen2.5-0.5b", "model_id": chat_model_id, "messages": [{"role": "user", "content": "你好"}]},
            headers=headers,
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["response"] == "reply:你好"

        # 3. A trainable base model is registered from the same registry.
        base_dir = environment["models"] / "qwen2.5-1.5b-base"
        base_dir.mkdir()
        (base_dir / "config.json").write_text(
            '{"architectures": ["Qwen2ForCausalLM"], "model_type": "qwen2", "max_position_embeddings": 32768}',
            encoding="utf-8",
        )
        (base_dir / "model.safetensors").write_bytes(b"weights")
        base = client.post(
            "/api/v1/models/install",
            json={"name": "qwen2.5-1.5b-base", "provider": "local", "path": str(base_dir)},
            headers=headers,
        ).json()

        trainable = client.get("/api/v1/models", params={"capability": "TRAINING"}, headers=headers).json()
        assert [item["id"] for item in trainable] == [base["id"]]
        # The GGUF chat model must never appear as a training base.
        assert chat_model_id not in {item["id"] for item in trainable}

        # 4. Train against it and register the produced adapter.
        dataset = b'{"text": "hello world"}\n' * 3
        upload = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("e2e.jsonl", dataset, "application/json")},
            headers=headers,
        )
        assert upload.status_code == 200, upload.text
        dataset_id = upload.json()["id"]
        started = client.post(
            "/api/v1/train/start",
            json={
                "dataset_id": dataset_id,
                "base_model_id": base["id"],
                "method": "lora",
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
        # The subprocess received the registry-resolved base model path.
        assert status["config"]["base_model_id"] == base["id"]
        assert status["config"]["base_model"] == str(base_dir)

        output_dir = status["output_dir"]
        with open(os.path.join(output_dir, "adapter_config.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        with open(os.path.join(output_dir, "adapter_model.safetensors"), "wb") as handle:
            handle.write(b"adapter")

        registered = client.post(
            f"/api/v1/train/{task_id}/register-model", json={"confirm": True}, headers=headers
        )
        assert registered.status_code == 200, registered.text
        artifact = registered.json()
        assert artifact["capabilities"] == ["LORA"]
        assert artifact["base_model_id"] == base["id"]
        assert artifact["metadata"]["training_task_id"] == task_id

        # 5. The adapter shows up in the model center but is not offered as chat.
        combined = client.get("/api/v1/models", headers=headers).json()
        assert artifact["id"] in {item["id"] for item in combined}
        chat_ids = {item["id"] for item in client.get("/api/v1/models", params={"capability": "CHAT"}, headers=headers).json()}
        assert artifact["id"] not in chat_ids

        # 6. Unloading the chat model releases the runtime for the next one.
        assert client.post(f"/api/v1/models/{chat_model_id}/unload", headers=headers).status_code == 200
        assert client.get(f"/api/v1/models/{chat_model_id}/runtime", headers=headers).json()["active"] is False
        assert client.post(f"/api/v1/models/{base['id']}/load", json={}, headers=headers).status_code == 200
        assert client.get(f"/api/v1/models/{base['id']}/runtime", headers=headers).json()["status"] == "loaded"
