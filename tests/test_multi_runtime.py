"""V1.2 Multi-Runtime: adapter catalog, resolver, registry columns, health API."""

from __future__ import annotations

import json
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import services.model_runtime_manager as runtime_module  # noqa: E402
from core.database import Base, SessionLocal  # noqa: E402
from main import app  # noqa: E402
from models.records import RemoteProviderConfig  # noqa: E402
from services.model_registry import ModelRegistry  # noqa: E402
from services.model_runtime_manager import ModelRuntimeManager  # noqa: E402
from services.runtime_resolver import RuntimeResolver  # noqa: E402
from services.runtimes.adapters import (  # noqa: E402
    LLAMA_CPP,
    OLLAMA,
    REMOTE_OPENAI,
    TRANSFORMERS,
)


class RecordingEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": "ok"}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "ok"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "models"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_catalog_exposes_the_documented_adapters():
    catalog = {adapter.id: adapter for adapter in RuntimeResolver.catalog()}

    assert set(catalog) == {LLAMA_CPP, TRANSFORMERS, OLLAMA, REMOTE_OPENAI}
    assert catalog[LLAMA_CPP].capabilities == frozenset({"CHAT", "INFERENCE"})
    assert "EMBEDDING" in catalog[REMOTE_OPENAI].capabilities
    assert catalog[REMOTE_OPENAI].local is False
    for adapter in catalog.values():
        assert isinstance(adapter.dependency_available(), bool)


def test_resolver_picks_llama_cpp_for_gguf_and_transformers_for_hf(session, tmp_path):
    registry = ModelRegistry(session)
    gguf = tmp_path / "models" / "chat.gguf"
    gguf.write_bytes(b"GGUF")
    hf = tmp_path / "models" / "hf-base"
    hf.mkdir()
    (hf / "config.json").write_text("{}", encoding="utf-8")
    (hf / "model.safetensors").write_bytes(b"w")

    gguf_record = registry.register(name="chat", provider="local", path=str(gguf), user_id=1)
    hf_record = registry.register(name="hf-base", provider="local", path=str(hf), user_id=1)

    # A GGUF file can only be read by llama.cpp; transformers must not claim it.
    assert gguf_record.supported_runtime_list() == [LLAMA_CPP]
    assert gguf_record.preferred_runtime == LLAMA_CPP
    assert hf_record.supported_runtime_list() == [TRANSFORMERS]
    assert hf_record.preferred_runtime == TRANSFORMERS

    # An explicit override wins when that adapter can actually read the asset.
    assert RuntimeResolver.resolve(hf_record, TRANSFORMERS) == TRANSFORMERS
    # Unsuitable or unknown overrides fall back to the supported adapter.
    assert RuntimeResolver.resolve(gguf_record, TRANSFORMERS) == LLAMA_CPP
    assert RuntimeResolver.resolve(hf_record, LLAMA_CPP) == TRANSFORMERS
    assert RuntimeResolver.resolve(gguf_record, "nonsense") == LLAMA_CPP
    assert RuntimeResolver.resolve(hf_record, None) == TRANSFORMERS


def test_manager_records_the_runtime_it_used(session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: RecordingEngine(path)),
    )
    registry = ModelRegistry(session)
    asset = tmp_path / "models" / "chat.gguf"
    asset.write_bytes(b"GGUF")
    record = registry.register(name="chat", provider="local", path=str(asset), user_id=1)
    hf = tmp_path / "models" / "hf"
    hf.mkdir()
    (hf / "config.json").write_text("{}", encoding="utf-8")
    (hf / "model.safetensors").write_bytes(b"w")
    hf_record = registry.register(name="hf", provider="local", path=str(hf), user_id=1)
    manager = runtime_module.get_model_runtime_manager()

    import asyncio

    instance = asyncio.run(manager.load(record.id, 1, db=session))
    assert instance.runtime_id == LLAMA_CPP
    assert instance.runtime_type == "llama.cpp"

    forced = asyncio.run(manager.load(hf_record.id, 1, db=session, runtime=TRANSFORMERS))
    assert forced.runtime_id == TRANSFORMERS
    assert forced.runtime_type == "transformers"

    # Re-loading the already loaded model with the same adapter is idempotent.
    again = asyncio.run(manager.load(hf_record.id, 1, db=session, runtime=TRANSFORMERS))
    assert again is forced


def test_remote_models_enter_the_registry(session, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    registry = ModelRegistry(session)
    session.add(
        RemoteProviderConfig(
            user_id=1,
            name="DeepSeek",
            base_url="https://api.deepseek.com",
            protocol="chat_completions",
            default_model="deepseek-chat",
            key_ciphertext="ciphertext",
            verification_status="success",
            verified_models_json=json.dumps(["deepseek-chat", "deepseek-reasoner"]),
        )
    )
    session.commit()

    remote = registry.remote_model_descriptors(1)

    assert {item["name"] for item in remote} == {"deepseek-chat", "deepseek-reasoner"}
    entry = remote[0]
    assert entry["source"] == "remote"
    assert entry["preferred_runtime"] == REMOTE_OPENAI
    assert entry["runtime_status"] == "remote"
    assert entry["ready"] is True
    assert entry["model_ref"].startswith("provider:")
    # Credentials never leave the server.
    assert "ciphertext" not in json.dumps(remote)


def _auth(client: TestClient) -> dict:
    username = f"v12{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_runtimes_api_reports_inventory_and_health(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        headers = _auth(client)
        asset = models / "runtime.gguf"
        asset.write_bytes(b"GGUF")
        client.post(
            "/api/v1/models/install",
            json={"name": "runtime", "provider": "local", "path": str(asset)},
            headers=headers,
        )

        listing = client.get("/api/v1/runtimes", headers=headers)
        assert listing.status_code == 200, listing.text
        runtimes = {item["id"]: item for item in listing.json()["runtimes"]}
        assert set(runtimes) == {LLAMA_CPP, TRANSFORMERS, OLLAMA, REMOTE_OPENAI}
        assert runtimes[LLAMA_CPP]["model_count"] == 1
        assert runtimes[TRANSFORMERS]["model_count"] == 0

        health = client.get(f"/api/v1/runtimes/{LLAMA_CPP}/health", headers=headers)
        assert health.status_code == 200
        detail = health.json()
        assert detail["local"] is True
        assert any(check["name"] == "dependency" for check in detail["checks"])
        assert any(check["name"] == "models" for check in detail["checks"])

        missing = client.get("/api/v1/runtimes/nope/health", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "RUNTIME_NOT_FOUND"


def test_models_api_merges_remote_entries(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        headers = _auth(client)
        user_id = int(client.get("/api/v1/auth/me", headers=headers).json()["id"])
        with SessionLocal() as session:
            session.add(
                RemoteProviderConfig(
                    user_id=user_id,
                    name="Remote",
                    base_url="https://api.example.test",
                    protocol="chat_completions",
                    default_model="remote-chat",
                    key_ciphertext="ciphertext",
                    verification_status="success",
                    verified_models_json=json.dumps(["remote-chat"]),
                )
            )
            session.commit()

        everything = client.get("/api/v1/models", headers=headers).json()
        assert any(item["source"] == "remote" and item["name"] == "remote-chat" for item in everything)

        only_remote = client.get("/api/v1/models", params={"source": "remote"}, headers=headers).json()
        assert [item["name"] for item in only_remote] == ["remote-chat"]
        assert only_remote[0]["preferred_runtime"] == REMOTE_OPENAI
