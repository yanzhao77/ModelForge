"""Runtime adapters (V1.2).

Every inference backend is described once: what it is called, which assets it
can serve, whether its dependency is installed, and how to build its engine.
`RuntimeResolver` uses this catalog to turn a `ModelRecord` into one adapter, so
the runtime manager never hard-codes llama.cpp/Transformers again.

Adapters are intentionally thin: the engines themselves (`LocalRuntime`,
`OllamaRuntime`, `OpenAIRuntime`) keep doing the work.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

LLAMA_CPP = "llama_cpp"
TRANSFORMERS = "transformers"
TRANSFORMERS_EMBEDDING = "transformers_embedding"
OLLAMA = "ollama"
REMOTE_OPENAI = "remote_openai"

_GGUF_SUFFIXES = {".gguf", ".ggml"}
_TRANSFORMERS_SUFFIXES = {".safetensors", ".bin", ".pt", ".pth"}
_TRANSFORMERS_FORMATS = {"safetensors", "transformers", "pytorch", "bin", "pt", "pth"}


def _dependency_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _is_gguf_container(record) -> bool:
    model_format = (getattr(record, "format", None) or "").lower()
    path = getattr(record, "path", None)
    suffix = Path(str(path)).suffix.lower() if path else ""
    if model_format in {"gguf", "ggml"} or suffix in _GGUF_SUFFIXES:
        return True
    if path and Path(str(path)).is_dir():
        try:
            return any(Path(str(path)).glob("*.gguf"))
        except OSError:
            return False
    return False


def _is_transformers_container(record) -> bool:
    model_format = (getattr(record, "format", None) or "").lower()
    if model_format in _TRANSFORMERS_FORMATS:
        return True
    path = getattr(record, "path", None)
    if not path:
        return False
    candidate = Path(str(path))
    if candidate.suffix.lower() in _TRANSFORMERS_SUFFIXES:
        return True
    return candidate.is_dir() and (candidate / "config.json").exists()


def _has_capability(record, capability: str) -> bool:
    values = getattr(record, "capability_list", lambda: [])() or []
    return capability.upper() in {str(item).upper() for item in values}


def _is_transformers_generation_container(record) -> bool:
    return _is_transformers_container(record) and not _has_capability(record, "EMBEDDING")


def _is_transformers_embedding_container(record) -> bool:
    return _is_transformers_container(record) and _has_capability(record, "EMBEDDING")


@dataclass(frozen=True)
class RuntimeAdapterSpec:
    """Static description of one inference backend."""

    id: str
    label: str
    capabilities: frozenset[str]
    requires_dependency: tuple[str, ...] = ()
    local: bool = True
    description: str = ""
    supports: Callable[[Any], bool] | None = None
    create_engine: Callable[[Any, str], Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def supports_model(self, record) -> bool:
        if self.supports is not None:
            return bool(self.supports(record))
        return True

    def dependency_available(self) -> bool:
        return all(_dependency_available(module) for module in self.requires_dependency)

    def missing_dependencies(self) -> list[str]:
        return [module for module in self.requires_dependency if not _dependency_available(module)]

    def build_engine(self, record, model_path: str) -> Any:
        if self.create_engine is None:
            raise NotImplementedError(f"runtime {self.id} does not create a local engine")
        return self.create_engine(record, model_path)


def _llama_cpp_engine(record, model_path: str) -> Any:  # noqa: ARG001 - adapter contract
    from services.runtimes.local_runtime import LocalRuntime

    return LocalRuntime(model_path=model_path)


def _transformers_engine(record, model_path: str) -> Any:  # noqa: ARG001 - adapter contract
    from services.runtimes.local_runtime import LocalRuntime

    return LocalRuntime(model_path=model_path)


def _transformers_embedding_engine(record, model_path: str) -> Any:  # noqa: ARG001 - adapter contract
    from services.runtimes.embedding_runtime import EmbeddingRuntime

    return EmbeddingRuntime(model_path=model_path)


def _ollama_engine(record, model_path: str) -> Any:  # noqa: ARG001 - adapter contract
    from core.config import settings
    from services.ollama_runtime import OllamaRuntime

    return OllamaRuntime(settings.ollama_base_url)


LLAMA_CPP_ADAPTER = RuntimeAdapterSpec(
    id=LLAMA_CPP,
    label="llama.cpp",
    capabilities=frozenset({"CHAT", "INFERENCE"}),
    requires_dependency=("llama_cpp",),
    description="GGUF weights served in-process by llama-cpp-python.",
    supports=_is_gguf_container,
    create_engine=_llama_cpp_engine,
)

TRANSFORMERS_ADAPTER = RuntimeAdapterSpec(
    id=TRANSFORMERS,
    label="transformers",
    capabilities=frozenset({"CHAT", "INFERENCE", "EMBEDDING"}),
    requires_dependency=("transformers",),
    description="Hugging Face checkpoints served in-process by transformers.",
    # A GGUF file cannot be read by transformers, so it is *not* supported here:
    # unsupported combinations must be reported, never attempted.
    supports=_is_transformers_generation_container,
    create_engine=_transformers_engine,
)

TRANSFORMERS_EMBEDDING_ADAPTER = RuntimeAdapterSpec(
    id=TRANSFORMERS_EMBEDDING,
    label="transformers-embedding",
    capabilities=frozenset({"EMBEDDING"}),
    requires_dependency=("transformers", "torch"),
    description="Hugging Face encoder checkpoints served in-process by transformers.",
    supports=_is_transformers_embedding_container,
    create_engine=_transformers_embedding_engine,
)

OLLAMA_ADAPTER = RuntimeAdapterSpec(
    id=OLLAMA,
    label="ollama",
    capabilities=frozenset({"CHAT", "INFERENCE"}),
    description="Local Ollama daemon (model pulled by tag).",
    supports=lambda record: False,  # never auto-selected from a registry asset
    create_engine=_ollama_engine,
)

REMOTE_OPENAI_ADAPTER = RuntimeAdapterSpec(
    id=REMOTE_OPENAI,
    label="remote_openai",
    capabilities=frozenset({"CHAT", "INFERENCE", "EMBEDDING"}),
    local=False,
    description="OpenAI-compatible remote provider; credentials stay encrypted.",
    supports=lambda record: False,
)

ADAPTERS: dict[str, RuntimeAdapterSpec] = {
    LLAMA_CPP: LLAMA_CPP_ADAPTER,
    TRANSFORMERS: TRANSFORMERS_ADAPTER,
    TRANSFORMERS_EMBEDDING: TRANSFORMERS_EMBEDDING_ADAPTER,
    OLLAMA: OLLAMA_ADAPTER,
    REMOTE_OPENAI: REMOTE_OPENAI_ADAPTER,
}


def get_adapter(runtime_id: str | None) -> RuntimeAdapterSpec | None:
    if not runtime_id:
        return None
    return ADAPTERS.get(str(runtime_id).strip().lower())


def adapter_catalog() -> list[RuntimeAdapterSpec]:
    return list(ADAPTERS.values())
