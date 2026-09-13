"""Cross-module integration: download -> registry -> training -> runtime.

Each test exercises one hop of the unified model lifecycle contract that the
runtime rework was built for:

* a finished download registers itself;
* training resolves its base model through the registry (and refuses an
  inference-only GGUF base);
* a training artefact re-enters the registry with the right capabilities.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.config import settings  # noqa: E402
from core.database import Base, SessionLocal  # noqa: E402
from main import app  # noqa: E402
from models.records import DownloadTaskRecord, ModelRecord, TrainTask  # noqa: E402
from services.downloader import downloader  # noqa: E402
from services.model_registry import ModelRegistry  # noqa: E402
from services.resource_lease import training_lease  # noqa: E402
from services.training import TrainingService, get_training_service  # noqa: E402


def _auth(client: TestClient) -> dict:
    username = f"lifecycle{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Download -> registry
# ---------------------------------------------------------------------------


def test_completed_download_registers_its_model(tmp_path, monkeypatch):
    models = tmp_path / "models"
    repo_dir = models / "TheBloke_demo-GGUF"
    repo_dir.mkdir(parents=True)
    (repo_dir / "demo.Q4_K_M.gguf").write_bytes(b"GGUF-placeholder")
    monkeypatch.setattr(settings, "model_dir", str(models))
    monkeypatch.setattr(settings, "model_path", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("MODEL_PATH", str(models))

    with TestClient(app) as client:
        headers = _auth(client)
        with SessionLocal() as session:
            task = DownloadTaskRecord(
                id=uuid.uuid4().hex,
                user_id=1,  # replaced below with the real account id
                repo_id="TheBloke/demo-GGUF",
                status="COMPLETED",
                progress=100,
                message="Download completed",
            )
            session.add(task)
            session.commit()
            task_id = task.id
        # Bind the task to the authenticated account.
        account_id = int(client.get("/api/v1/auth/me", headers=headers).json()["id"])
        with SessionLocal() as session:
            session.get(DownloadTaskRecord, task_id).user_id = account_id
            session.commit()

        downloader._register_completed_download(task_id)
        # Re-running the registration must not create a duplicate row.
        downloader._register_completed_download(task_id)

        listed = client.get("/api/v1/models", headers=headers).json()
        registered = [item for item in listed if item["name"] == "demo.Q4_K_M"]
        assert len(registered) == 1
        assert registered[0]["capabilities"] == ["CHAT", "INFERENCE"]
        assert registered[0]["provider"] == "download"
        assert registered[0]["ready"] is True


# ---------------------------------------------------------------------------
# Training -> registry base model resolution
# ---------------------------------------------------------------------------


@pytest.fixture
def training_env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "train_output_dir", str(outputs))

    import services.training as training_module

    monkeypatch.setattr(training_module, "_torch_available", lambda: True)
    monkeypatch.setattr(
        training_module.TrainingService, "_launch", lambda self, cfg, state, log: MagicMock(poll=lambda: 0, returncode=0, terminate=lambda: None)
    )
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield {"session": session, "models": models, "outputs": outputs}
    session.close()
    Base.metadata.drop_all(bind=engine)
    # The training lease is process-wide: release it so the next test (or file)
    # is not answered with TRAINING_BUSY.
    holder = training_lease.holder()
    if holder is not None:
        training_lease.release(user_id=holder.user_id)


def _dataset(session, tmp_path, user_id=1):
    from models.records import Dataset

    path = tmp_path / "dataset.jsonl"
    path.write_text('{"text": "hello"}\n', encoding="utf-8")
    row = Dataset(user_id=user_id, name="ds", file_path=str(path), original_name="dataset.jsonl", format="jsonl", row_count=1)
    session.add(row)
    session.commit()
    return row


def test_training_refuses_an_inference_only_gguf_base(training_env, tmp_path):
    session = training_env["session"]
    gguf = training_env["models"] / "chat-only.gguf"
    gguf.write_bytes(b"GGUF-placeholder")
    record = ModelRegistry(session).register(name="chat-only", provider="local", path=str(gguf), user_id=1)
    dataset = _dataset(session, tmp_path)

    with pytest.raises(ValueError):
        TrainingService().start(
            session,
            1,
            {"dataset_id": dataset.id, "base_model_id": record.id, "method": "lora", "epochs": 1},
        )


def test_training_resolves_base_model_path_from_registry(training_env, tmp_path):
    session = training_env["session"]
    base_dir = training_env["models"] / "llama-base"
    base_dir.mkdir()
    (base_dir / "config.json").write_text('{"model_type": "llama"}', encoding="utf-8")
    (base_dir / "model.safetensors").write_bytes(b"weights")
    record = ModelRegistry(session).register(name="llama-base", provider="local", path=str(base_dir), user_id=1)
    dataset = _dataset(session, tmp_path)

    task = TrainingService().start(
        session,
        1,
        {"dataset_id": dataset.id, "base_model_id": record.id, "base_model": "ignored", "method": "lora", "epochs": 1},
    )

    config = json.loads(task.config)
    # The subprocess consumes the resolved path; the row keeps the label.
    assert Path(config["base_model"]).resolve() == base_dir.resolve()
    assert task.base_model == "llama-base"
    assert config["base_model_id"] == record.id


def test_training_artifact_registers_as_lora_adapter(training_env, tmp_path):
    session = training_env["session"]
    base_dir = training_env["models"] / "llama-base"
    base_dir.mkdir()
    (base_dir / "config.json").write_text('{"model_type": "llama"}', encoding="utf-8")
    (base_dir / "model.safetensors").write_bytes(b"weights")
    base = ModelRegistry(session).register(name="llama-base", provider="local", path=str(base_dir), user_id=1)
    dataset = _dataset(session, tmp_path)
    service = TrainingService()
    task = service.start(
        session,
        1,
        {"dataset_id": dataset.id, "base_model_id": base.id, "method": "lora", "epochs": 1},
    )
    # Simulate a finished run whose output contains an adapter.
    output = Path(task.output_dir)
    (output / "adapter_config.json").write_text("{}", encoding="utf-8")
    (output / "adapter_model.safetensors").write_bytes(b"adapter")
    task.status = "done"
    session.commit()

    registered = service.register_model(session, task.task_id, 1)

    assert registered["provider"] == "training"
    assert registered["capabilities"] == ["LORA"]
    assert registered["base_model_id"] == base.id
    assert registered["metadata"]["training_task_id"] == task.task_id
    assert registered["metadata"]["requires_base_model"] is True
    # A LoRA adapter must not be offered as a chat/training base.
    rows = ModelRegistry(session).list_models(1, capability="TRAINING")
    assert base.name in {row.name for row in rows}
    assert registered["name"] not in {row.name for row in rows}


def test_full_finetune_artifact_is_a_chat_model(training_env, tmp_path):
    session = training_env["session"]
    dataset = _dataset(session, tmp_path)
    service = TrainingService()
    task = service.start(session, 1, {"dataset_id": dataset.id, "base_model": "meta-llama/Llama-3", "method": "full", "epochs": 1})
    output = Path(task.output_dir)
    (output / "config.json").write_text('{"model_type": "llama"}', encoding="utf-8")
    (output / "model.safetensors").write_bytes(b"weights")
    task.status = "done"
    session.commit()

    registered = service.register_model(session, task.task_id, 1)

    assert registered["capabilities"] == ["CHAT", "INFERENCE"]
    assert registered["format"] == "safetensors"
    # The record name must not contain path separators from the repo id.
    assert "/" not in registered["name"]


def test_training_registration_requires_a_finished_task(training_env, tmp_path):
    session = training_env["session"]
    dataset = _dataset(session, tmp_path)
    service = TrainingService()
    task = service.start(session, 1, {"dataset_id": dataset.id, "base_model": "m", "method": "lora", "epochs": 1})

    with pytest.raises(ValueError):
        service.register_model(session, task.task_id, 1)
