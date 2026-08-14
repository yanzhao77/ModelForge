"""Runtime registry: lazy per-backend runtime instances with LRU-ish eviction."""
from typing import Dict, Optional

from core.config import settings
from services.ollama_runtime import OllamaRuntime


class RuntimeRegistry:
    """Registry that lazily creates runtime engines by name and delegates calls.

    Default runtime is Ollama. Local (transformers/gguf) and OpenAI-compatible
    runtimes are created on demand without importing heavy deps at startup.
    """

    MAX_RUNTIMES = 3

    def __init__(self):
        self._runtimes: Dict[str, object] = {}
        self._default = "ollama"

    def get(self, name: Optional[str] = None) -> object:
        name = name or self._default
        if name not in self._runtimes:
            if len(self._runtimes) >= self.MAX_RUNTIMES:
                # evict the first (oldest) runtime
                self._runtimes.pop(next(iter(self._runtimes)))
            self._runtimes[name] = self._create(name)
        return self._runtimes[name]

    def _create(self, name: str) -> object:
        if name == "ollama":
            return OllamaRuntime(settings.ollama_base_url)
        if name in ("local", "local-gguf", "local-transformers"):
            from services.runtimes.local_runtime import LocalRuntime
            return LocalRuntime()
        if name == "openai":
            from services.runtimes.openai_api_runtime import OpenAIRuntime
            return OpenAIRuntime()
        raise ValueError(f"Unknown runtime: {name}")

    async def load(self, model_name: str, **kwargs) -> Dict:
        return await self.get().load(model_name, **kwargs)

    async def chat(self, model_name: str, messages: list, **kwargs) -> Dict:
        return await self.get().chat(model_name, messages, **kwargs)

    async def stop(self, model_name: str, **kwargs) -> Dict:
        return await self.get().stop(model_name, **kwargs)

    def status(self) -> Dict:
        return {
            "default": self._default,
            "runtimes": {k: type(v).__name__ for k, v in self._runtimes.items()},
        }


registry = RuntimeRegistry()

def get_runtime() -> RuntimeRegistry:
    return registry