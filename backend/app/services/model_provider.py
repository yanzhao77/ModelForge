"""Model Provider system - unified interface for downloading models from various sources."""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class ModelProvider(ABC):
    """Abstract base for model providers (HuggingFace, ModelScope, etc.)."""

    @abstractmethod
    def download(self, model_id: str, save_dir: Optional[str] = None) -> str:
        """Download a model and return the local path."""
        ...

    @abstractmethod
    def list_models(self, query: str = "", limit: int = 20) -> List[Dict]:
        """List available models matching the query."""
        ...
