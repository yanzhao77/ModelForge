"""Ollama Runtime Engine implementation."""
from typing import Dict, Optional

import httpx

from .runtime import RuntimeEngine


class OllamaRuntime(RuntimeEngine):
    """Runtime backed by a local Ollama server."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    async def load(self, model_name: str, **kwargs) -> Dict:
        """Ensure a model is available in Ollama (pull if needed)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Check if model exists
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            names = [m.get("name", "") for m in models]

            if model_name not in names:
                # Pull the model
                pull_resp = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"name": model_name},
                )
                pull_resp.raise_for_status()

            return {"status": "loaded", "model": model_name}

    async def chat(self, model_name: str, messages: list, **kwargs) -> Dict:
        """Send a chat request to Ollama."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": False,
            }
            payload.update(kwargs)
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            result = resp.json()
            return {
                "model": model_name,
                "content": result.get("message", {}).get("content", ""),
                "raw": result,
            }

    async def stop(self, model_name: str) -> Dict:
        """Unload a model from memory (Ollama handles this implicitly)."""
        return {"status": "stopped", "model": model_name}
