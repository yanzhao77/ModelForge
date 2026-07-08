"""Runtime Engine - abstract interface for model inference runtimes."""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Optional


class RuntimeEngine(ABC):
    """Abstract runtime engine for model inference."""

    @abstractmethod
    async def load(self, model_name: str, **kwargs) -> Dict:
        """Load/prepare a model for inference."""
        ...

    @abstractmethod
    async def chat(self, model_name: str, messages: list, **kwargs) -> Dict:
        """Run a chat completion."""
        ...

    @abstractmethod
    async def stop(self, model_name: str) -> Dict:
        """Stop/unload a model."""
        ...
