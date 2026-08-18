"""Model Provider system - unified interface for downloading models from various sources."""
from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """Abstract base for model providers (HuggingFace, ModelScope, etc.)."""

    @abstractmethod
    def download(self, model_id: str, save_dir: str | None = None) -> str:
        """Download a model and return the local path."""
        ...

    @abstractmethod
    def list_models(self, query: str = "", limit: int = 20) -> list[dict]:
        """List available models matching the query."""
        ...
