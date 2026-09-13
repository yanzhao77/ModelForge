"""Unified model registry: capability detection, filters and lifecycle.

These tests pin the invariants the rest of the product depends on:

* capabilities come from the asset format, never from its file name;
* a GGUF inference file is never advertised as trainable;
* a record whose declared file disappeared is not a usable target;
* re-registering the same asset updates one row instead of duplicating it.
"""

from __future__ import annotations

import os
import struct
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.database import Base  # noqa: E402
from models.records import ModelRecord  # noqa: E402
from services.model_metadata import detect_metadata  # noqa: E402
from services.model_registry import ModelRegistry, ModelRegistryError  # noqa: E402


def _gguf_bytes(architecture: str = "llama", context_length: int = 4096) -> bytes:
    """Build a minimal valid GGUF header for metadata tests."""
    payload = bytearray(b"GGUF")
    payload += struct.pack("<I", 3)  # version
    payload += struct.pack("<Q", 0)  # tensor count
    payload += struct.pack("<Q", 2)  # kv count
    for key, value in (
        ("general.architecture", architecture),
        (f"{architecture}.context_length", context_length),
    ):
        encoded = key.encode("utf-8")
        payload += struct.pack("<Q", len(encoded)) + encoded
        if isinstance(value, str):
            raw = value.encode("utf-8")
            payload += struct.pack("<I", 8) + struct.pack("<Q", len(raw)) + raw
        else:
            payload += struct.pack("<I", 4) + struct.pack("<I", value)
    return bytes(payload)


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "models"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def registry(session):
    return ModelRegistry(session)


@pytest.fixture
def model_root(tmp_path):
    return tmp_path / "models"


def test_gguf_gets_chat_and_inference_only(registry, model_root):
    asset = model_root / "qwen-q4_k_m.gguf"
    asset.write_bytes(_gguf_bytes())

    record = registry.register(name="qwen-q4", provider="download", path=str(asset), user_id=1)

    assert record.capability_list() == ["CHAT", "INFERENCE"]
    assert registry.supports(record, "CHAT") is True
    # A GGUF file must never be handed to the fine-tuning pipeline.
    assert registry.supports(record, "TRAINING") is False
    assert record.status == "ready"
    assert record.format == "gguf"
    assert record.size_bytes == asset.stat().st_size


def test_transformers_directory_is_trainable(registry, model_root):
    asset = model_root / "llama-base"
    asset.mkdir()
    (asset / "config.json").write_text(
        '{"architectures": ["LlamaForCausalLM"], "model_type": "llama", "max_position_embeddings": 8192}',
        encoding="utf-8",
    )
    (asset / "model.safetensors").write_bytes(b"weights")

    record = registry.register(name="llama-base", provider="local", path=str(asset), user_id=1)

    assert set(record.capability_list()) == {"CHAT", "INFERENCE", "TRAINING", "LORA"}
    assert record.format == "safetensors"
    assert record.metadata_dict()["architecture"] == "LlamaForCausalLM"
    assert record.metadata_dict()["context_length"] == 8192


def test_lora_adapter_is_not_advertised_as_chat(registry, model_root):
    asset = model_root / "user-1" / "adapter"
    asset.mkdir(parents=True)
    (asset / "adapter_config.json").write_text("{}", encoding="utf-8")
    (asset / "adapter_model.safetensors").write_bytes(b"weights")

    record = registry.register(
        name="lora-ft",
        provider="training",
        path=str(asset),
        user_id=1,
        model_format="peft-adapter",
        base_model_id=7,
    )

    assert record.capability_list() == ["LORA"]
    assert registry.supports(record, "CHAT") is False
    assert record.base_model_id == 7


def test_unknown_format_defaults_to_inference(registry, model_root):
    asset = model_root / "mystery.weights"
    asset.write_bytes(b"x")

    record = registry.register(name="mystery", provider="local", path=str(asset), user_id=1)

    assert record.capability_list() == ["INFERENCE"]


def test_capability_filter_and_duplicate_protection(registry, model_root):
    trainable = model_root / "trainable"
    trainable.mkdir()
    (trainable / "config.json").write_text("{}", encoding="utf-8")
    (trainable / "pytorch_model.bin").write_bytes(b"w")
    chat = model_root / "chat.gguf"
    chat.write_bytes(_gguf_bytes())

    registry.register(name="trainable", provider="local", path=str(trainable), user_id=1)
    registry.register(name="chat", provider="download", path=str(chat), user_id=1)
    # Re-registering the same asset must update, not duplicate.
    registry.register(name="chat", provider="download", path=str(chat), user_id=1)

    all_models = registry.list_models(1)
    assert len(all_models) == 2
    chat_models = registry.list_models(1, capability="CHAT")
    assert {record.name for record in chat_models} == {"trainable", "chat"}
    training_models = registry.list_models(1, capability="TRAINING")
    assert {record.name for record in training_models} == {"trainable"}


def test_registry_is_user_scoped(registry, model_root):
    asset = model_root / "private.gguf"
    asset.write_bytes(_gguf_bytes())
    record = registry.register(name="private", provider="local", path=str(asset), user_id=1)

    assert registry.get(record.id, user_id=1) is not None
    assert registry.get(record.id, user_id=2) is None


def test_path_outside_model_root_is_rejected(registry, tmp_path):
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(_gguf_bytes())

    with pytest.raises(ModelRegistryError) as excinfo:
        registry.register(name="outside", provider="local", path=str(outside), user_id=1)

    assert excinfo.value.code == "MODEL_PATH_OUTSIDE_ALLOWED_ROOT"


def test_missing_file_is_not_ready_and_refreshes_to_invalid(registry, model_root):
    asset = model_root / "gone.gguf"
    asset.write_bytes(_gguf_bytes())
    record = registry.register(name="gone", provider="local", path=str(asset), user_id=1)
    assert registry.is_ready(record) is True

    asset.unlink()
    registry.refresh(record, commit=True)

    assert record.status == "invalid"
    assert registry.is_ready(record) is False
    with pytest.raises(ModelRegistryError) as excinfo:
        registry.require_ready(record)
    assert excinfo.value.code == "MODEL_NOT_READY"


def test_registered_but_absent_asset_is_installed(registry, model_root):
    record = registry.register(
        name="pending", provider="local", path=str(model_root / "pending.gguf"), user_id=1
    )

    assert record.status == "installed"
    assert registry.is_ready(record) is False


def test_backfill_capabilities_fills_legacy_rows(registry, session, model_root):
    asset = model_root / "legacy.gguf"
    asset.write_bytes(_gguf_bytes())
    session.add(
        ModelRecord(user_id=1, name="legacy", provider="local", path=str(asset), status="available")
    )
    session.commit()

    updated = registry.backfill_capabilities(user_id=1)

    assert updated == 1
    record = registry.list_models(1)[0]
    assert record.capability_list() == ["CHAT", "INFERENCE"]


def test_default_model_round_trip(registry, model_root):
    asset = model_root / "default.gguf"
    asset.write_bytes(_gguf_bytes())
    record = registry.register(name="default-model", provider="local", path=str(asset), user_id=1)

    assert registry.default_model(1) is None
    registry.set_default(1, record.id)
    assert registry.default_model(1).id == record.id
    # Another account must not inherit this preference.
    assert registry.default_model(2) is None


def test_gguf_metadata_reader(tmp_path):
    asset = tmp_path / "meta.gguf"
    asset.write_bytes(_gguf_bytes(architecture="qwen2", context_length=32768))

    metadata = detect_metadata(str(asset))

    assert metadata["architecture"] == "qwen2"
    assert metadata["context_length"] == 32768


def test_metadata_detection_never_raises_on_garbage(tmp_path):
    asset = tmp_path / "broken.gguf"
    asset.write_bytes(b"not-a-gguf-at-all")

    assert detect_metadata(str(asset)) == {}
