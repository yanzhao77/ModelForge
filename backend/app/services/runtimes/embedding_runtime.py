"""Local embedding runtime backed by Transformers AutoModel."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable

from services.embedding_service import EMBEDDING_TOKEN_LIMIT, _l2_normalize


class EmbeddingRuntime:
    """Load and serve embedding-only Hugging Face checkpoints."""

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path
        self._tokenizer = None
        self._model = None
        self._lock = threading.Lock()

    async def load(self, model_name: str, **kwargs) -> dict:  # noqa: ARG002 - runtime API compatibility
        await asyncio.to_thread(self._locked, self._load_sync, model_name)
        return {"status": "loaded", "model": model_name}

    async def stop(self, model_name: str) -> dict:
        await asyncio.to_thread(self._locked, self._stop_sync)
        return {"status": "stopped", "model": model_name}

    async def embed(self, model_name: str, texts: Iterable[str]) -> list[list[float]]:
        if self._model is None:
            await self.load(model_name)
        return await asyncio.to_thread(self._locked, self._embed_sync, list(texts))

    def _locked(self, func, *args, **kwargs):
        with self._lock:
            return func(*args, **kwargs)

    def _load_sync(self, model_name: str) -> None:
        path = self.model_path or model_name
        from transformers import AutoModel, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=False)
        self._model = AutoModel.from_pretrained(path, trust_remote_code=False)
        self._model.eval()

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
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

    def _stop_sync(self) -> None:
        try:
            if self._model is not None:
                del self._model
            if self._tokenizer is not None:
                del self._tokenizer
        finally:
            self._model = None
            self._tokenizer = None

