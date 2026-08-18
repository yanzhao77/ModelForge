"""Runtime Engine - abstract interface for model inference runtimes."""
from abc import ABC, abstractmethod


class RuntimeEngine(ABC):
    """Abstract runtime engine for model inference."""

    @abstractmethod
    async def load(self, model_name: str, **kwargs) -> dict:
        """Load/prepare a model for inference."""
        ...

    @abstractmethod
    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        """Run a chat completion."""
        ...

    @abstractmethod
    async def stop(self, model_name: str) -> dict:
        """Stop/unload a model."""
        ...
