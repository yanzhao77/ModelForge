"""Local model import detection, registration, and safety boundaries."""

from __future__ import annotations

import os
import struct
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from api.models import _operation_descriptors  # noqa: E402
from core.config import settings  # noqa: E402
from core.database import Base  # noqa: E402
from services.local_model_importer import (  # noqa: E402
    ExternalModelPathAuthorizer,
    LocalModelDetector,
    LocalModelImportError,
    validate_manual_capabilities,
)
from services.model_registry import ModelRegistry, ModelRegistryError  # noqa: E402


def _gguf_bytes(architecture: str = "llama", context_length: int = 4096) -> bytes:
    payload = bytearray(b"GGUF")
    payload += struct.pack("<I", 3)
    payload += struct.pack("<Q", 0)
    payload += struct.pack("<Q", 2)
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


def _write_wan_snapshot(root):
    root.mkdir(parents=True)
    (root / "model_index.json").write_text(
        '{"_class_name":"WanPipeline","scheduler":["diffusers","UniPCMultistepScheduler"],"text_encoder":["transformers","UMT5EncoderModel"],"tokenizer":["transformers","T5TokenizerFast"],"transformer":["diffusers","WanTransformer3DModel"],"vae":["diffusers","AutoencoderKLWan"]}',
        encoding="utf-8",
    )
    for child in ("scheduler", "text_encoder", "tokenizer", "transformer", "vae"):
        (root / child).mkdir()
    (root / "scheduler" / "scheduler_config.json").write_text('{"_class_name":"UniPCMultistepScheduler"}', encoding="utf-8")
    (root / "text_encoder" / "config.json").write_text('{"architectures":["UMT5EncoderModel"]}', encoding="utf-8")
    (root / "tokenizer" / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (root / "tokenizer" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "transformer" / "config.json").write_text('{"_class_name":"WanTransformer3DModel"}', encoding="utf-8")
    (root / "vae" / "config.json").write_text('{"_class_name":"AutoencoderKLWan"}', encoding="utf-8")
    (root / "transformer" / "diffusion_pytorch_model.safetensors.index.json").write_text(
        '{"metadata":{"total_size":2},"weight_map":{"a":"diffusion_pytorch_model-00001-of-00001.safetensors"}}',
        encoding="utf-8",
    )
    (root / "transformer" / "diffusion_pytorch_model-00001-of-00001.safetensors").write_bytes(b"tr")
    (root / "text_encoder" / "model.safetensors.index.json").write_text(
        '{"metadata":{"total_size":2},"weight_map":{"a":"model-00001-of-00001.safetensors"}}',
        encoding="utf-8",
    )
    (root / "text_encoder" / "model-00001-of-00001.safetensors").write_bytes(b"te")
    (root / "vae" / "diffusion_pytorch_model.safetensors").write_bytes(b"vae")


@pytest.fixture
def session(tmp_path, monkeypatch):
    model_root = tmp_path / "models"
    data_dir = tmp_path / "data"
    model_root.mkdir()
    data_dir.mkdir()
    monkeypatch.setenv("MODEL_PATH", str(model_root))
    monkeypatch.setenv("MODEL_DIR", str(model_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(settings, "model_path", str(model_root))
    monkeypatch.setattr(settings, "model_dir", str(model_root))
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_detects_external_gguf_without_copying(session, tmp_path):
    external = tmp_path / "外部 模型" / "tiny.gguf"
    external.parent.mkdir()
    external.write_bytes(_gguf_bytes("qwen2", 8192))

    detection = LocalModelDetector().detect(str(external)).payload

    assert detection["format"] == "gguf"
    assert detection["architecture"] == "qwen2"
    assert detection["capabilities"] == ["CHAT", "INFERENCE"]
    assert "GGUF" in " ".join(detection["evidence"])

    record = ModelRegistry(session).register_detected_local(detection=detection, user_id=1)
    assert record.path == str(external.resolve())
    assert record.provider == "local_external"
    assert ModelRegistry(session).resolve_path(record) == str(external.resolve())


def test_duplicate_external_registration_updates_one_row(session, tmp_path):
    external = tmp_path / "external" / "dup.gguf"
    external.parent.mkdir()
    external.write_bytes(_gguf_bytes())
    detection = LocalModelDetector().detect(str(external)).payload
    registry = ModelRegistry(session)

    first = registry.register_detected_local(detection=detection, user_id=1, name="first")
    second = registry.register_detected_local(detection=detection, user_id=1, name="second")

    assert first.id == second.id
    assert [record.name for record in registry.list_models(1)] == ["second"]


def test_external_record_requires_authorization_file(session, tmp_path):
    external = tmp_path / "external" / "locked.gguf"
    external.parent.mkdir()
    external.write_bytes(_gguf_bytes())
    detection = LocalModelDetector().detect(str(external)).payload
    record = ModelRegistry(session).register_detected_local(detection=detection, user_id=1)
    (tmp_path / "data" / "local_model_paths.json").unlink()

    with pytest.raises(ModelRegistryError) as excinfo:
        ModelRegistry(session).resolve_path(record)

    assert excinfo.value.code == "MODEL_PATH_INVALID"


def test_symlink_uses_real_path_authorization(session, tmp_path):
    target = tmp_path / "external" / "real.gguf"
    target.parent.mkdir()
    target.write_bytes(_gguf_bytes())
    link = tmp_path / "models" / "linked.gguf"
    link.symlink_to(target)

    detection = LocalModelDetector().detect(str(link)).payload
    record = ModelRegistry(session).register_detected_local(detection=detection, user_id=1)

    assert record.path == str(target.resolve())
    assert ExternalModelPathAuthorizer().is_authorized(1, target)


def test_hf_config_does_not_guess_from_weight_extension(session, tmp_path):
    directory = tmp_path / "external" / "broken-hf"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text("{not json", encoding="utf-8")
    (directory / "model.safetensors").write_bytes(b"weights")

    detection = LocalModelDetector().detect(str(directory)).payload

    assert detection["capabilities"] == []
    assert detection["uncertain"]
    with pytest.raises(LocalModelImportError) as excinfo:
        validate_manual_capabilities(detection, None)
    assert excinfo.value.code == "LOCAL_MODEL_CAPABILITY_UNCERTAIN"


def test_missing_shards_are_reported(session, tmp_path):
    directory = tmp_path / "external" / "sharded"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(
        '{"architectures":["LlamaForCausalLM"],"model_type":"llama"}',
        encoding="utf-8",
    )
    (directory / "model.safetensors.index.json").write_text(
        '{"weight_map":{"a":"model-00001-of-00002.safetensors","b":"model-00002-of-00002.safetensors"}}',
        encoding="utf-8",
    )
    (directory / "model-00001-of-00002.safetensors").write_bytes(b"one")

    detection = LocalModelDetector().detect(str(directory)).payload

    assert "model-00002-of-00002.safetensors" in detection["missing_files"]
    assert detection["runnable"] is False


def test_lora_adapter_is_not_independently_loadable(session, tmp_path):
    directory = tmp_path / "external" / "adapter"
    directory.mkdir(parents=True)
    (directory / "adapter_config.json").write_text('{"base_model_name_or_path":"base/llama"}', encoding="utf-8")
    (directory / "adapter_model.safetensors").write_bytes(b"adapter")

    detection = LocalModelDetector().detect(str(directory)).payload

    assert detection["is_adapter"] is True
    assert detection["capabilities"] == ["LORA"]
    assert detection["runnable"] is False
    assert validate_manual_capabilities(detection, ["LORA"]) == ["LORA"]
    with pytest.raises(LocalModelImportError):
        validate_manual_capabilities(detection, ["CHAT"])


def test_embedding_model_cannot_be_default_chat_model(session, tmp_path):
    directory = tmp_path / "external" / "embedder"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(
        '{"architectures":["BertModel"],"model_type":"bert"}',
        encoding="utf-8",
    )
    (directory / "model.safetensors").write_bytes(b"weights")
    (directory / "tokenizer.json").write_text("{}", encoding="utf-8")
    detection = LocalModelDetector().detect(str(directory)).payload
    registry = ModelRegistry(session)
    record = registry.register_detected_local(detection=detection, user_id=1)

    assert record.capability_list() == ["EMBEDDING"]
    with pytest.raises(ModelRegistryError) as excinfo:
        registry.set_default(1, record.id)
    assert excinfo.value.code == "MODEL_DEFAULT_UNSUPPORTED"


def test_detects_wan_diffusers_as_video_without_name_guessing(session, tmp_path):
    directory = tmp_path / "external" / "snapshot-with-neutral-name"
    _write_wan_snapshot(directory)

    detection = LocalModelDetector().detect(str(directory)).payload

    assert detection["format"] == "diffusers"
    assert detection["architecture"] == "WanPipeline"
    assert detection["capabilities"] == ["VIDEO"]
    assert detection["metadata"]["wan_validation"]["ok"] is True
    assert any(item["id"] == "wan-diffusers" for item in detection["runtime_options"])
    assert detection["supported_runtimes"] == []


def test_unknown_diffusers_pipeline_is_not_defaulted_to_image(session, tmp_path):
    directory = tmp_path / "external" / "custom-diffusers"
    directory.mkdir(parents=True)
    (directory / "model_index.json").write_text('{"_class_name":"CustomPipeline"}', encoding="utf-8")

    detection = LocalModelDetector().detect(str(directory)).payload

    assert detection["capabilities"] == []
    assert detection["runnable"] is False
    assert "IMAGE" not in detection["capabilities"]


def test_repair_existing_wan_record_preserves_id_and_corrects_capability(session, tmp_path):
    directory = tmp_path / "external" / "wan-record"
    _write_wan_snapshot(directory)
    detection = LocalModelDetector().detect(str(directory)).payload
    registry = ModelRegistry(session)
    record = registry.register_detected_local(detection=detection, user_id=1, name="kept-name")
    original_id = record.id
    record.set_capabilities(["IMAGE"])
    record.set_metadata({"model_index": {"_class_name": "WanPipeline"}, "local_import": {"authorized_path": str(directory.resolve())}})
    session.commit()

    changed = registry.repair_detected_local_record(record, commit=True)

    assert changed is True
    assert record.id == original_id
    assert record.name == "kept-name"
    assert record.capability_list() == ["VIDEO"]
    assert record.metadata_dict()["local_import"]["authorized_path"] == str(directory.resolve())


def test_wan_operations_only_expose_video_examples_when_available(session, tmp_path, monkeypatch):
    monkeypatch.setattr("services.local_model_importer.missing_wan_dependencies", lambda: [])
    directory = tmp_path / "external" / "wan-operations"
    _write_wan_snapshot(directory)
    detection = LocalModelDetector().detect(str(directory)).payload
    registry = ModelRegistry(session)
    record = registry.register_detected_local(detection=detection, user_id=1, name="wan-ops")

    available = _operation_descriptors(record, registry)

    assert [operation["id"] for operation in available["operations"]] == ["video-generation"]
    assert set(available["api_examples"]) == {"videos"}
    assert "/v1/videos" in available["api_examples"]["videos"]

    metadata = record.metadata_dict()
    metadata.setdefault("local_import", {})["load_validation"] = {
        "status": "failed",
        "message": "load-only validation stopped by memory guard",
    }
    record.set_metadata(metadata)
    session.commit()

    unavailable = _operation_descriptors(record, registry)
    operation = unavailable["operations"][0]
    assert operation["id"] == "video-generation"
    assert operation["available"] is False
    assert operation["endpoints"] == []
    assert "example" not in operation
    assert unavailable["api_examples"] == {}
