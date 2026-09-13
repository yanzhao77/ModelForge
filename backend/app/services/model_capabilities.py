"""Model capability + lifecycle taxonomy for the unified model registry.

ModelForge is not a single-purpose runtime: one ``ModelRecord`` may be an
inference-only GGUF file, a trainable Hugging Face checkpoint, or a LoRA adapter
that only makes sense next to a base model. Pages used to guess what a model
could do from its file name, so the same asset could be "chat capable" on one
screen and "not trainable" on another.

This module is the single place that decides:

* which capabilities an asset has (``CHAT`` / ``INFERENCE`` / ``TRAINING`` / …);
* which lifecycle statuses are valid and which count as "ready".

It contains no I/O and no framework imports so the rules stay testable and can
be reused by the API, the desktop client and the training service.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class ModelCapability(str, Enum):
    """Capabilities a model asset may expose to the rest of the product."""

    CHAT = "CHAT"
    INFERENCE = "INFERENCE"
    VISION = "VISION"
    EMBEDDING = "EMBEDDING"
    TRAINING = "TRAINING"
    LORA = "LORA"
    AUDIO = "AUDIO"
    IMAGE = "IMAGE"


class CapabilityFilter:
    """Parsing helpers for ``?capability=CHAT`` style query filters."""

    @staticmethod
    def parse(value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip().upper()
        try:
            return ModelCapability(candidate).value
        except ValueError as exc:
            raise ValueError(f"UNKNOWN_MODEL_CAPABILITY:{value}") from exc


class ModelStatus(str, Enum):
    """Persisted lifecycle status of a model asset."""

    DISCOVERED = "discovered"
    INSTALLING = "installing"
    INSTALLED = "installed"
    READY = "ready"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    LOAD_FAILED = "load_failed"
    INVALID = "invalid"
    # ``available`` predates the lifecycle work and is still returned by the
    # desktop client and readiness snapshot. It means exactly the same thing as
    # ``ready``, so both are accepted everywhere the code asks "is it usable?".
    AVAILABLE = "available"


#: Statuses that mean "the bytes are present and the model can be loaded".
READY_STATUSES: frozenset[str] = frozenset(
    {
        ModelStatus.READY.value,
        ModelStatus.AVAILABLE.value,
        ModelStatus.INSTALLED.value,
        ModelStatus.LOADED.value,
    }
)

#: Statuses produced while the runtime owns the model.
TRANSIENT_STATUSES: frozenset[str] = frozenset(
    {ModelStatus.LOADING.value, ModelStatus.UNLOADING.value}
)

LOADABLE_STATUSES: frozenset[str] = READY_STATUSES | {ModelStatus.DISCOVERED.value}


def normalize_status(value: str | None, *, default: str = ModelStatus.READY.value) -> str:
    """Map a stored status onto the canonical lifecycle vocabulary."""
    if not value:
        return default
    candidate = str(value).strip().lower()
    try:
        return ModelStatus(candidate).value
    except ValueError:
        return default


def is_ready_status(value: str | None) -> bool:
    """Whether a model in this status can be loaded and used."""
    return normalize_status(value, default="") in READY_STATUSES


# --- capability detection -------------------------------------------------

_GGUF_SUFFIXES = {".gguf", ".ggml"}
_TRANSFORMERS_SUFFIXES = {".safetensors", ".bin", ".pt", ".pth"}
_ADAPTER_FORMATS = {"peft-adapter", "lora", "adapter"}
_TRANSFORMERS_FORMATS = {"safetensors", "transformers", "pytorch", "bin", "pt", "pth"}
_GGUF_FORMATS = {"gguf", "ggml"}
_CONFIG_INDICATORS = ("config.json", "tokenizer.json", "tokenizer_config.json")
#: Sentence-Transformers artefacts: presence marks an embedding-only model.
_EMBEDDING_MARKERS = ("sentence_bert_config.json", "modules.json", "1_Pooling/config.json")


def _suffix_of(path: str | None) -> str:
    if not path:
        return ""
    return Path(str(path)).suffix.lower()


def _is_directory(path: str | None) -> bool:
    return bool(path) and Path(str(path)).is_dir()


def is_embedding_asset(path: str | None) -> bool:
    """Whether a model directory declares itself as a sentence-embedding model."""
    if not _is_directory(path):
        return False
    base = Path(str(path))
    return any((base / marker).exists() for marker in _EMBEDDING_MARKERS)


def normalize_format(model_format: str | None, path: str | None = None) -> str | None:
    """Best-effort format label for an asset when the record has none."""
    if model_format:
        cleaned = str(model_format).strip().lower()
        if cleaned:
            return cleaned
    suffix = _suffix_of(path)
    if suffix in _GGUF_SUFFIXES:
        return "gguf"
    if suffix in _TRANSFORMERS_SUFFIXES:
        return "safetensors"
    if _is_directory(path) and any((Path(str(path)) / name).exists() for name in _CONFIG_INDICATORS):
        return "safetensors"
    return None


def infer_capabilities(
    *,
    model_format: str | None = None,
    path: str | None = None,
    provider: str | None = None,
    quant: str | None = None,
) -> list[str]:
    """Derive the capabilities of one asset from its format and location.

    The rules deliberately under-promise: a GGUF file is never assumed to be
    ``TRAINING`` capable just because it is a "model", and a LoRA adapter is
    never advertised as ``CHAT`` until the runtime can actually mount it on top
    of its base model.
    """
    del quant  # reserved: quantisation never changes the capability set
    fmt = normalize_format(model_format, path)
    is_training_output = (provider or "").strip().lower() == "training"

    if fmt in _ADAPTER_FORMATS:
        # Adapters are only usable together with a base model. The runtime does
        # not mount them yet, so they must not be advertised as chat capable.
        return [ModelCapability.LORA.value]
    if fmt in _GGUF_FORMATS:
        return [ModelCapability.CHAT.value, ModelCapability.INFERENCE.value]
    if is_embedding_asset(path):
        # An embedding model cannot chat; advertising CHAT would let Chat/Agent
        # try to generate from a BERT-style encoder.
        return [ModelCapability.EMBEDDING.value]
    if fmt in _TRANSFORMERS_FORMATS:
        # Hugging Face checkpoints are the format the training pipeline consumes,
        # so they may serve as training bases. GGUF files never reach this branch.
        if is_training_output:
            return [ModelCapability.CHAT.value, ModelCapability.INFERENCE.value]
        return [
            ModelCapability.CHAT.value,
            ModelCapability.INFERENCE.value,
            ModelCapability.TRAINING.value,
            ModelCapability.LORA.value,
        ]
    return [ModelCapability.INFERENCE.value]


def default_capabilities_for_download(*, filename: str | None, repo_id: str | None) -> list[str]:
    """Capabilities for a repository that just finished downloading."""
    return infer_capabilities(
        model_format=None,
        path=filename or repo_id,
        provider="download",
    )
