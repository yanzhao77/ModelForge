"""Local model import detection and controlled external-path authorization.

This module is deliberately offline-only. It reads small JSON/config headers and
bounded GGUF metadata from a user-selected local path, but it never downloads
missing files, installs dependencies, or executes model repository code.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import settings
from services.model_capabilities import ModelCapability, normalize_format
from services.model_metadata import detect_metadata, directory_size_bytes
from services.runtimes.adapters import ADAPTERS
from services.wan_video_runtime import (
    WAN_RUNTIME_NAME,
    missing_wan_dependencies,
    validate_wan_diffusers_snapshot,
)


class LocalModelImportError(ValueError):
    """Stable failure used by the model API."""

    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


_TEXT_GENERATION_ARCH_HINTS = (
    "ForCausalLM",
    "CausalLM",
    "LMHeadModel",
    "ForConditionalGeneration",
)
_MULTIMODAL_ARCH_HINTS = (
    "Llava",
    "Qwen2VL",
    "Qwen2_5_VL",
    "Mllama",
    "Vision2Seq",
    "Blip",
    "Kosmos",
)
_EMBEDDING_ARCH_HINTS = ("BertModel", "RobertaModel", "XLMRobertaModel", "MPNetModel", "Nomic")
_RERANKER_ARCH_HINTS = ("ForSequenceClassification", "CrossEncoder")
_WEIGHT_NAMES = (
    "model.safetensors",
    "pytorch_model.bin",
    "tf_model.h5",
    "flax_model.msgpack",
)
_WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth")
_INDEX_NAMES = ("model.safetensors.index.json", "pytorch_model.bin.index.json")
_TOKENIZER_MARKERS = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "vocab.txt", "merges.txt")
_PROCESSOR_MARKERS = ("processor_config.json", "preprocessor_config.json", "image_processor_config.json")
_SENTENCE_TRANSFORMER_MARKERS = ("sentence_bert_config.json", "modules.json", "1_Pooling/config.json")


def _json_read(path: Path) -> tuple[dict | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as exc:
        return None, type(exc).__name__
    return (payload, None) if isinstance(payload, dict) else (None, "not_object")


def _real_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise LocalModelImportError("LOCAL_MODEL_PATH_REQUIRED", "请选择模型目录或文件。")
    try:
        return Path(text).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise LocalModelImportError(
            "LOCAL_MODEL_PATH_NOT_FOUND",
            "所选模型路径不存在。",
            {"path": text},
            http_status=404,
        ) from exc
    except OSError as exc:
        raise LocalModelImportError(
            "LOCAL_MODEL_PATH_UNREADABLE",
            "无法访问所选模型路径，请检查权限。",
            {"path": text},
            http_status=403,
        ) from exc


def _can_read(path: Path) -> bool:
    if not os.access(path, os.R_OK):
        return False
    if path.is_dir():
        return os.access(path, os.X_OK)
    return True


def _format_size(bytes_value: int) -> str:
    amount = float(max(0, int(bytes_value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f}{unit}"
        amount /= 1024
    return f"{amount:.1f}PB"


def _adapter_payload(capabilities: list[str], model_format: str | None) -> list[dict]:
    result: list[dict] = []
    cap_set = set(capabilities)
    for adapter in ADAPTERS.values():
        if not adapter.local:
            continue
        # Ollama serves models by daemon tag; it does not load arbitrary files
        # selected from disk, so it is not an import-time runtime option.
        if adapter.id == "ollama":
            continue
        # The detailed supports_model check needs a ModelRecord; for detection
        # we only expose runtime families that match the inferred operation set.
        relevant = bool(cap_set & set(adapter.capabilities))
        if adapter.id == "llama_cpp" and model_format not in {"gguf", "ggml"}:
            relevant = False
        if adapter.id.startswith("transformers") and model_format not in {"safetensors", "transformers", "pytorch", "bin", "pt", "pth"}:
            relevant = False
        if adapter.id == "transformers" and cap_set == {ModelCapability.EMBEDDING.value}:
            relevant = False
        if adapter.id == "transformers_embedding" and ModelCapability.EMBEDDING.value not in cap_set:
            relevant = False
        if not relevant:
            continue
        missing = adapter.missing_dependencies()
        result.append(
            {
                "id": adapter.id,
                "label": adapter.label,
                "available": not missing,
                "missing_dependencies": missing,
                "capabilities": sorted(adapter.capabilities),
                "parameters": _runtime_parameters(adapter.id),
            }
        )
    return result


def _runtime_parameters(runtime_id: str) -> list[dict]:
    if runtime_id == "llama_cpp":
        return [
            {"name": "context_length", "type": "integer", "default": 4096, "minimum": 1},
            {"name": "gpu_layers", "type": "integer", "default": 0, "minimum": -1},
            {"name": "threads", "type": "integer", "default": 0, "minimum": 0},
        ]
    if runtime_id in {"transformers", "transformers_embedding"}:
        return [
            {"name": "device", "type": "select", "values": ["auto", "cpu", "cuda", "mps"], "default": "auto"},
            {"name": "precision", "type": "select", "values": ["auto", "float32", "float16"], "default": "auto"},
        ]
    return []


def _wan_runtime_payload(path: Path) -> dict:
    missing = missing_wan_dependencies()
    return {
        "id": WAN_RUNTIME_NAME,
        "label": "Wan Diffusers",
        "available": not missing,
        "missing_dependencies": missing,
        "capabilities": [ModelCapability.VIDEO.value],
        "parameters": [
            {"name": "profile", "type": "select", "values": ["wan21-t2v-1.3b-mps-smoke-5f-256x256", "wan21-t2v-1.3b-mps-short-9f-320x192"], "default": "wan21-t2v-1.3b-mps-smoke-5f-256x256"},
            {"name": "device", "type": "select", "values": ["mps"], "default": "mps"},
            {"name": "placement", "type": "select", "values": ["model-cpu-offload"], "default": "model-cpu-offload"},
        ],
        "local_files_only": True,
        "path": str(path),
    }


@dataclass
class DetectionResult:
    payload: dict[str, Any]

    @property
    def capabilities(self) -> list[str]:
        return list(self.payload.get("capabilities") or [])

    @property
    def model_format(self) -> str | None:
        value = self.payload.get("format")
        return str(value) if value else None


class LocalModelDetector:
    """Offline local model detector with explicit uncertainty reporting."""

    def detect(self, raw_path: str) -> DetectionResult:
        path = _real_path(raw_path)
        if not _can_read(path):
            raise LocalModelImportError(
                "LOCAL_MODEL_PATH_UNREADABLE",
                "无法读取所选模型路径，请检查权限。",
                {"path": str(path)},
                http_status=403,
            )
        payload = self._base_payload(path)
        if path.is_file():
            self._detect_file(path, payload)
        elif path.is_dir():
            self._detect_directory(path, payload)
        else:
            raise LocalModelImportError(
                "LOCAL_MODEL_PATH_UNSUPPORTED",
                "所选路径不是普通文件或目录。",
                {"path": str(path)},
            )
        self._finalize(payload)
        return DetectionResult(payload)

    def _base_payload(self, path: Path) -> dict[str, Any]:
        return {
            "path": str(path),
            "real_path": str(path),
            "name": path.stem if path.is_file() else path.name,
            "display_name": path.stem if path.is_file() else path.name,
            "kind": "file" if path.is_file() else "directory",
            "format": None,
            "architecture": None,
            "task_categories": [],
            "capabilities": [],
            "model_type": "unknown",
            "is_adapter": False,
            "base_model_hint": None,
            "metadata": {},
            "evidence": [],
            "warnings": [],
            "missing_files": [],
            "uncertain": [],
            "supported_runtimes": [],
            "preferred_runtime": None,
            "runtime_options": [],
            "runnable": False,
            "unavailable_reasons": [],
            "size_bytes": directory_size_bytes(path),
        }

    def _detect_file(self, path: Path, payload: dict[str, Any]) -> None:
        suffix = path.suffix.lower()
        if suffix in {".gguf", ".ggml"}:
            metadata = detect_metadata(str(path), model_format="gguf")
            try:
                with path.open("rb") as handle:
                    has_magic = handle.read(4) == b"GGUF"
            except OSError:
                has_magic = False
            if metadata or has_magic:
                payload["format"] = suffix.removeprefix(".")
                payload["capabilities"] = [ModelCapability.CHAT.value, ModelCapability.INFERENCE.value]
                payload["task_categories"] = ["text-generation", "chat"]
                payload["model_type"] = "full"
                payload["metadata"].update(metadata)
                payload["architecture"] = metadata.get("architecture")
                payload["evidence"].append("GGUF magic/header metadata")
            else:
                payload["format"] = suffix.removeprefix(".")
                payload["uncertain"].append("File extension suggests GGUF/GGML, but the header was not valid.")
            return
        if suffix in _WEIGHT_SUFFIXES:
            payload["format"] = normalize_format(None, str(path)) or suffix.removeprefix(".")
            payload["uncertain"].append("A standalone weight file needs nearby config/tokenizer files before its task can be trusted.")
            payload["evidence"].append(f"Weight-like file extension: {suffix}")
            return
        payload["uncertain"].append("Unsupported or unknown model file extension.")

    def _detect_directory(self, path: Path, payload: dict[str, Any]) -> None:
        ggufs = sorted(item for item in path.glob("*.gguf") if item.is_file())
        if ggufs:
            primary = ggufs[0]
            metadata = detect_metadata(str(primary), model_format="gguf")
            payload["format"] = "gguf"
            payload["capabilities"] = [ModelCapability.CHAT.value, ModelCapability.INFERENCE.value]
            payload["task_categories"] = ["text-generation", "chat"]
            payload["model_type"] = "full"
            payload["metadata"].update(metadata | {"primary_file": primary.name})
            payload["architecture"] = metadata.get("architecture")
            payload["evidence"].append(f"Directory contains GGUF file: {primary.name}")
            return

        adapter_config, adapter_error = _json_read(path / "adapter_config.json")
        if adapter_config is not None or (path / "adapter_model.safetensors").exists() or (path / "adapter_model.bin").exists():
            payload["format"] = "peft-adapter"
            payload["model_type"] = "adapter"
            payload["is_adapter"] = True
            payload["capabilities"] = [ModelCapability.LORA.value]
            payload["task_categories"] = ["adapter"]
            payload["base_model_hint"] = (adapter_config or {}).get("base_model_name_or_path")
            payload["metadata"].update({"adapter_config": adapter_config or {}})
            payload["evidence"].append("PEFT/LoRA adapter_config.json or adapter weights")
            if not payload["base_model_hint"]:
                payload["warnings"].append("Adapter does not declare a base model; it cannot be loaded independently.")
            if adapter_error and adapter_error != "missing":
                payload["warnings"].append(f"adapter_config.json could not be parsed: {adapter_error}")
            return

        model_index, model_index_error = _json_read(path / "model_index.json")
        if model_index is not None:
            self._detect_diffusers(path, payload, model_index)
            return
        if model_index_error and model_index_error != "missing":
            payload["warnings"].append(f"model_index.json could not be parsed: {model_index_error}")

        config, config_error = _json_read(path / "config.json")
        if config is not None:
            self._detect_hf(path, payload, config)
            return
        if config_error and config_error != "missing":
            payload["format"] = "transformers"
            payload["warnings"].append(f"config.json could not be parsed: {config_error}")
            payload["uncertain"].append("Hugging Face config exists but is unreadable or invalid.")
            return

        payload["uncertain"].append("No GGUF, adapter_config.json, model_index.json, or config.json was found.")

    def _detect_diffusers(self, path: Path, payload: dict[str, Any], model_index: dict) -> None:
        class_name = str(model_index.get("_class_name") or "")
        payload["format"] = "diffusers"
        payload["architecture"] = class_name or None
        payload["model_type"] = "full"
        payload["metadata"].update({"model_index": {key: value for key, value in model_index.items() if key.startswith("_") or key in {"scheduler", "text_encoder", "tokenizer", "transformer", "vae", "unet"}}})
        payload["evidence"].append("Diffusers model_index.json")
        validation = validate_wan_diffusers_snapshot(path)
        if class_name == "WanPipeline" and validation.get("pipeline") == "WanPipeline":
            payload["capabilities"] = [ModelCapability.VIDEO.value]
            payload["task_categories"] = ["video-generation"]
            payload["metadata"]["wan_validation"] = validation
            payload["evidence"].append("WanPipeline with WanTransformer3DModel components")
            payload.setdefault("runtime_options", []).append(_wan_runtime_payload(path))
            if validation.get("missing_files"):
                payload["missing_files"].extend(validation.get("missing_files") or [])
            if validation.get("errors"):
                payload["uncertain"].extend(validation.get("errors") or [])
        elif class_name in {"StableDiffusionPipeline", "StableDiffusionXLPipeline", "FluxPipeline", "AutoPipelineForText2Image"}:
            payload["capabilities"] = [ModelCapability.IMAGE.value]
            payload["task_categories"] = ["image-generation"]
        else:
            payload["uncertain"].append(f"Unsupported or unknown Diffusers pipeline: {class_name or 'unknown'}.")
        for component in ("unet", "transformer", "vae", "text_encoder"):
            value = model_index.get(component)
            if value and not (path / component).exists():
                payload["missing_files"].append(component)

    def _detect_hf(self, path: Path, payload: dict[str, Any], config: dict) -> None:
        architectures = [str(item) for item in config.get("architectures") or [] if str(item).strip()]
        architecture = architectures[0] if architectures else None
        model_type = str(config.get("model_type") or "").strip()
        payload["format"] = "safetensors"
        payload["architecture"] = architecture
        payload["model_type"] = "full"
        payload["metadata"].update(detect_metadata(path, model_format="safetensors"))
        payload["metadata"].update({"model_type": model_type, "architectures": architectures})
        payload["evidence"].append("Hugging Face config.json")
        self._check_hf_files(path, payload)

        joined = " ".join(architectures + [model_type])
        has_processor = any((path / marker).exists() for marker in _PROCESSOR_MARKERS)
        has_sentence_transformer = any((path / marker).exists() for marker in _SENTENCE_TRANSFORMER_MARKERS)
        if any(hint in joined for hint in _MULTIMODAL_ARCH_HINTS) or has_processor:
            payload["capabilities"] = [ModelCapability.CHAT.value, ModelCapability.INFERENCE.value, ModelCapability.VISION.value]
            payload["task_categories"] = ["multimodal-understanding", "chat"]
        elif has_sentence_transformer or any(hint in joined for hint in _EMBEDDING_ARCH_HINTS):
            payload["capabilities"] = [ModelCapability.EMBEDDING.value]
            payload["task_categories"] = ["embedding"]
            payload["evidence"].append("Embedding-style architecture or sentence-transformers marker")
        elif any(hint in joined for hint in _RERANKER_ARCH_HINTS):
            payload["capabilities"] = [ModelCapability.RERANKER.value]
            payload["task_categories"] = ["reranker"]
        elif any(hint in joined for hint in _TEXT_GENERATION_ARCH_HINTS):
            payload["capabilities"] = [ModelCapability.CHAT.value, ModelCapability.INFERENCE.value, ModelCapability.TRAINING.value]
            payload["task_categories"] = ["text-generation", "chat"]
        else:
            payload["uncertain"].append("config.json does not identify a supported task architecture.")

    def _check_hf_files(self, path: Path, payload: dict[str, Any]) -> None:
        found_weights = any((path / name).exists() for name in _WEIGHT_NAMES)
        found_weights = found_weights or any(item.is_file() and item.suffix.lower() in _WEIGHT_SUFFIXES for item in path.glob("*"))
        found_index = False
        for index_name in _INDEX_NAMES:
            index_path = path / index_name
            if not index_path.exists():
                continue
            found_index = True
            index, err = _json_read(index_path)
            if err:
                payload["warnings"].append(f"{index_name} could not be parsed: {err}")
                continue
            weight_map = index.get("weight_map") if isinstance(index, dict) else None
            if isinstance(weight_map, dict):
                for shard in sorted(set(str(value) for value in weight_map.values())):
                    if not (path / shard).exists():
                        payload["missing_files"].append(shard)
        if not found_weights and not found_index:
            payload["missing_files"].append("model weights")
        if not any((path / marker).exists() for marker in _TOKENIZER_MARKERS):
            payload["warnings"].append("Tokenizer files were not found; text generation may be unavailable.")

    def _finalize(self, payload: dict[str, Any]) -> None:
        payload["format"] = normalize_format(payload.get("format"), payload.get("real_path")) or payload.get("format")
        metadata = payload.get("metadata") or {}
        if payload.get("architecture") is None and metadata.get("architecture"):
            payload["architecture"] = metadata.get("architecture")
        if payload["size_bytes"]:
            payload["size"] = _format_size(payload["size_bytes"])
        else:
            payload["size"] = ""
        runtimes = list(payload.get("runtime_options") or [])
        runtimes.extend(_adapter_payload(payload.get("capabilities") or [], payload.get("format")))
        payload["runtime_options"] = runtimes
        # ``supported_runtimes`` remains the chat/embedding load-runtime list
        # consumed by ModelRuntimeManager. Video runtimes stay in metadata and
        # the video registry, so a video model is not loaded through chat.
        payload["supported_runtimes"] = [item["id"] for item in runtimes if item["id"] in ADAPTERS]
        payload["preferred_runtime"] = payload["supported_runtimes"][0] if payload["supported_runtimes"] else None
        runnable_caps = {ModelCapability.CHAT.value, ModelCapability.INFERENCE.value, ModelCapability.EMBEDDING.value, ModelCapability.VIDEO.value}
        dependency_ok = any(item["available"] for item in runtimes)
        payload["runnable"] = bool(set(payload.get("capabilities") or []) & runnable_caps and dependency_ok and not payload.get("missing_files"))
        if payload.get("missing_files"):
            payload["unavailable_reasons"].append("Required model files are missing.")
        if not payload.get("capabilities"):
            payload["unavailable_reasons"].append("Model capability is uncertain and must be selected manually.")
        if runtimes and not dependency_ok:
            payload["unavailable_reasons"].append("Required runtime dependencies are not installed.")
        if payload.get("is_adapter"):
            payload["unavailable_reasons"].append("Adapters require a compatible base model and cannot be loaded independently yet.")
            payload["runnable"] = False
        if payload.get("format") == "diffusers" and ModelCapability.VIDEO.value not in payload.get("capabilities", []):
            payload["unavailable_reasons"].append("Diffusers image runtime is not connected in this build.")
            payload["runnable"] = False
        if ModelCapability.RERANKER.value in payload.get("capabilities", []):
            payload["unavailable_reasons"].append("Reranker runtime is not connected in this build.")
            payload["runnable"] = False
        payload["requires_manual_confirmation"] = bool(payload.get("uncertain"))


class ExternalModelPathAuthorizer:
    """Persist exact external paths that a user explicitly registered."""

    def __init__(self, data_dir: str | Path | None = None):
        self._data_dir = Path(str(data_dir or settings.data_dir)).expanduser()
        if not self._data_dir.is_absolute():
            self._data_dir = Path(__file__).resolve().parents[3] / self._data_dir
        self._path = self._data_dir / "local_model_paths.json"
        self._lock = threading.RLock()

    def authorize(self, user_id: int | None, path: str | Path) -> str:
        resolved = _real_path(str(path))
        if not _can_read(resolved):
            raise LocalModelImportError(
                "LOCAL_MODEL_PATH_UNREADABLE",
                "无法读取所选模型路径，请检查权限。",
                {"path": str(resolved)},
                http_status=403,
            )
        user_key = str(user_id or "global")
        with self._lock:
            data = self._read()
            paths = data.setdefault(user_key, [])
            if str(resolved) not in paths:
                paths.append(str(resolved))
            data["updated_at"] = dt.datetime.utcnow().isoformat() + "Z"
            self._write(data)
        return str(resolved)

    def is_authorized(self, user_id: int | None, path: str | Path) -> bool:
        try:
            resolved = _real_path(str(path))
        except LocalModelImportError:
            return False
        with self._lock:
            data = self._read()
        allowed = set(data.get(str(user_id or "global"), [])) | set(data.get("global", []))
        return str(resolved) in allowed

    def _read(self) -> dict:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)


def validate_manual_capabilities(detected: dict, requested: list[str] | None) -> list[str]:
    """Return requested capabilities after rejecting incompatible overrides."""
    detected_caps = [str(item).upper() for item in detected.get("capabilities") or []]
    requested_caps = [str(item).strip().upper() for item in (requested or []) if str(item).strip()]
    if not requested_caps:
        if not detected_caps:
            raise LocalModelImportError(
                "LOCAL_MODEL_CAPABILITY_UNCERTAIN",
                "无法确定模型类别，请手动选择可验证的类别。",
                {"uncertain": detected.get("uncertain") or []},
            )
        return detected_caps
    allowed = set(detected_caps)
    if detected.get("is_adapter"):
        allowed = {ModelCapability.LORA.value}
    if detected.get("format") == "gguf":
        allowed = {ModelCapability.CHAT.value, ModelCapability.INFERENCE.value}
    if detected.get("format") == "diffusers":
        allowed = {ModelCapability.IMAGE.value, ModelCapability.VIDEO.value} & set(detected_caps)
    invalid = [cap for cap in requested_caps if cap not in allowed]
    if invalid:
        raise LocalModelImportError(
            "LOCAL_MODEL_CAPABILITY_CONFLICT",
            "手动选择的类别与检测到的架构或格式不兼容。",
            {"requested": requested_caps, "detected": detected_caps, "invalid": invalid},
        )
    return requested_caps
