"""Runtime Resolver (V1.2): ``ModelRecord → supported runtimes → adapter``.

The runtime manager must not decide "llama.cpp vs Transformers" by itself.
This resolver owns that decision so it can be reused by the runtimes API, the
model registry (which persists `supported_runtimes`) and any future provider.
"""

from __future__ import annotations

from services.runtimes.adapters import (
    ADAPTERS,
    LLAMA_CPP,
    OLLAMA,
    REMOTE_OPENAI,
    TRANSFORMERS,
    TRANSFORMERS_EMBEDDING,
    RuntimeAdapterSpec,
    adapter_catalog,
    get_adapter,
)

#: Preference order used when a model does not declare one. GGUF is served by
#: llama.cpp; Transformers checkpoints by transformers.
_DEFAULT_PRIORITY: tuple[str, ...] = (LLAMA_CPP, TRANSFORMERS_EMBEDDING, TRANSFORMERS)


class RuntimeResolver:
    """Static resolution helpers (no I/O, no DB)."""

    @staticmethod
    def supported_runtimes(record) -> list[str]:
        """Adapters that could serve ``record``, in preference order."""
        explicit = list(getattr(record, "supported_runtime_list", lambda: [])() or [])
        if explicit:
            return [item for item in explicit if item in ADAPTERS]
        return [runtime_id for runtime_id in _DEFAULT_PRIORITY if ADAPTERS[runtime_id].supports_model(record)]

    @staticmethod
    def resolve(record, preferred: str | None = None) -> str | None:
        """Pick the runtime id to use for ``record``."""
        supported = RuntimeResolver.supported_runtimes(record)
        candidate = (preferred or getattr(record, "preferred_runtime", None) or "").strip().lower()
        if candidate:
            adapter = ADAPTERS.get(candidate)
            if adapter is not None and (candidate in supported or adapter.supports_model(record)):
                return candidate
        return supported[0] if supported else None

    @staticmethod
    def adapter(runtime_id: str | None) -> RuntimeAdapterSpec | None:
        return get_adapter(runtime_id)

    @staticmethod
    def create_engine(record, model_path: str, runtime_id: str | None = None):
        """Build the engine for ``record`` with the resolved (or given) adapter."""
        resolved = RuntimeResolver.resolve(record, runtime_id)
        if resolved is None:
            raise ValueError("NO_RUNTIME_AVAILABLE")
        adapter = ADAPTERS[resolved]
        engine = adapter.build_engine(record, model_path)
        return resolved, adapter, engine

    @staticmethod
    def catalog() -> list[RuntimeAdapterSpec]:
        return adapter_catalog()

    @staticmethod
    def is_local(runtime_id: str) -> bool:
        adapter = get_adapter(runtime_id)
        return bool(adapter and adapter.local)

    @staticmethod
    def label(runtime_id: str | None) -> str:
        adapter = get_adapter(runtime_id)
        return adapter.label if adapter else (runtime_id or "unknown")


__all__ = [
    "LLAMA_CPP",
    "OLLAMA",
    "REMOTE_OPENAI",
    "TRANSFORMERS",
    "TRANSFORMERS_EMBEDDING",
    "RuntimeResolver",
]
