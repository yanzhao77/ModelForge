"""Embedding providers (V1.4).

Two providers exist, and the caller always learns which one answered:

* ``hash`` — deterministic, dependency-free hashing embedder. Always available,
  used by the built-in knowledge base and as the fallback.
* ``transformers`` — a registry model whose ``EMBEDDING`` capability is
  declared, embedded through transformers with mean pooling. Only selected when
  the asset really is an embedding model and the AI stack is installed.

Nothing here silently upgrades an embedding-only model into a chat model: the
provider reports ``fallback`` + ``reason`` so the UI can be honest.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable

from core.text_tokens import iter_terms
from services.model_capabilities import ModelCapability
from services.model_registry import ModelRegistry, ModelRegistryError

DEFAULT_HASH_DIMENSION = 256
EMBEDDING_TOKEN_LIMIT = 512


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return values
    return [value / norm for value in values]


class HashEmbeddingProvider:
    """Deterministic bag-of-hashed-tokens embedding (no dependencies)."""

    name = "hash"
    local = True

    def __init__(self, dimension: int = DEFAULT_HASH_DIMENSION):
        self.dimension = max(16, int(dimension))

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in iter_terms(text or ""):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self.dimension
            vector[bucket] += 1.0
        return _l2_normalize(vector)

    def describe(self) -> dict:
        return {"provider": self.name, "dimension": self.dimension, "local": True, "fallback": False}


class TransformersEmbeddingProvider:
    """Mean-pooled embeddings from a registry model with EMBEDDING capability."""

    name = "transformers"
    local = True

    def __init__(self, model_path: str):
        self.model_path = model_path
        self._tokenizer = None
        self._model = None
        self.dimension: int | None = None

    @staticmethod
    def available() -> bool:
        import importlib.util

        try:
            return importlib.util.find_spec("transformers") is not None and importlib.util.find_spec("torch") is not None
        except (ImportError, ValueError):
            return False

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: F401
        from transformers import AutoModel, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=False)
        self._model = AutoModel.from_pretrained(self.model_path, trust_remote_code=False)
        self._model.eval()
        self.dimension = int(getattr(self._model.config, "hidden_size", 0) or 0) or None

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        self._ensure_model()
        import torch

        outputs: list[list[float]] = []
        for text in texts:
            encoded = self._tokenizer(
                text or "",
                return_tensors="pt",
                truncation=True,
                max_length=EMBEDDING_TOKEN_LIMIT,
            )
            with torch.inference_mode():
                hidden = self._model(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
            outputs.append(_l2_normalize([float(value) for value in pooled[0]]))
        return outputs

    def describe(self) -> dict:
        return {
            "provider": self.name,
            "dimension": self.dimension,
            "local": True,
            "fallback": False,
        }


def resolve_embedding_provider(db, user_id: int, model_id: int | None = None):
    """Return ``(provider, metadata)``; never raises for a missing model."""
    registry = ModelRegistry(db)
    record = None
    reason = None
    if model_id is not None:
        try:
            record = registry.require(int(model_id), user_id)
            registry.require_capability(record, ModelCapability.EMBEDDING.value)
        except ModelRegistryError as exc:
            return HashEmbeddingProvider(), {
                "provider": "hash",
                "fallback": True,
                "reason": exc.code,
                "model_id": model_id,
            }
    else:
        candidates = registry.list_models(user_id, capability=ModelCapability.EMBEDDING.value)
        record = candidates[0] if candidates else None
        if record is None:
            reason = "NO_EMBEDDING_MODEL_REGISTERED"

    if record is not None:
        if not TransformersEmbeddingProvider.available():
            return HashEmbeddingProvider(), {
                "provider": "hash",
                "fallback": True,
                "reason": "TRANSFORMERS_NOT_INSTALLED",
                "model_id": record.id,
                "model": record.name,
            }
        try:
            provider = TransformersEmbeddingProvider(registry.resolve_path(record))
            return provider, provider.describe() | {"model_id": record.id, "model": record.name, "fallback": False}
        except ModelRegistryError as exc:
            return HashEmbeddingProvider(), {
                "provider": "hash",
                "fallback": True,
                "reason": exc.code,
                "model_id": record.id,
            }
    return HashEmbeddingProvider(), {
        "provider": "hash",
        "fallback": True,
        "reason": reason or "HASH_EMBEDDER_SELECTED",
        "model_id": None,
    }


def describe_embedding_provider(db, user_id: int, model_id: int | None = None) -> dict:
    _provider, meta = resolve_embedding_provider(db, user_id, model_id=model_id)
    registry = ModelRegistry(db)
    embedding_models = registry.list_models(user_id, capability=ModelCapability.EMBEDDING.value)
    return {
        **meta,
        "default_provider": "hash",
        "transformers_available": TransformersEmbeddingProvider.available(),
        "registered_models": [
            {"model_id": record.id, "name": record.name, "format": record.format}
            for record in embedding_models
        ],
    }


def embed_texts(db, user_id: int, texts: list[str], *, model_id: int | None = None) -> dict:
    provider, meta = resolve_embedding_provider(db, user_id, model_id=model_id)
    from core.cache import embedding_cache

    namespace = f"embed:{meta.get('provider')}:{meta.get('model_id')}"
    vectors: list[list[float] | None] = []
    pending: list[tuple[int, str]] = []
    for index, text in enumerate(texts):
        cached = embedding_cache.get(namespace, embedding_cache.make_key(text))
        vectors.append(cached)
        if cached is None:
            pending.append((index, text))
    if pending:
        computed = provider.embed([text for _index, text in pending])
        for (index, text), vector in zip(pending, computed, strict=False):
            vectors[index] = vector
            embedding_cache.set(namespace, embedding_cache.make_key(text), vector)
    return {
        "vectors": vectors,
        "dimensions": len(vectors[0]) if vectors else 0,
        "count": len(vectors),
        "embedding": meta,
    }
