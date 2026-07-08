"""API Client for communicating with ModelForge backend."""
import httpx
from typing import List, Dict, Optional


class ModelForgeClient:
    """HTTP client for ModelForge REST API."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    # ---- Server info ----

    def get_info(self) -> Dict:
        """Get server info (name, version)."""
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{self.base_url}/")
            resp.raise_for_status()
            return resp.json()

    # ---- Models ----

    def list_models(self) -> List[Dict]:
        """List all registered models."""
        return self._get_json("/models")

    def scan_models(self, path: Optional[str] = None) -> List[Dict]:
        """Scan a directory for models."""
        params = {"path": path} if path else {}
        return self._post_json("/models/scan", params=params)

    def install_model(self, name: str, provider: str, path: str, size: str = "") -> Dict:
        """Register a model installation."""
        return self._post_json("/models/install", json={
            "name": name, "provider": provider, "path": path, "size": size
        })

    def remove_model(self, model_id: int) -> Dict:
        """Remove a model record."""
        return self._delete_json(f"/models/{model_id}")

    # ---- Runtime ----

    def runtime_start(self, model: str) -> Dict:
        """Load a model into runtime."""
        return self._post_json("/runtime/start", json={"model": model})

    def runtime_chat(self, model: str, messages: list) -> Dict:
        """Send a chat request."""
        return self._post_json("/runtime/chat", json={
            "model": model, "messages": messages
        })

    def runtime_stop(self, model: str) -> Dict:
        """Stop a runtime model."""
        return self._post_json("/runtime/stop", json={"model": model})

    # ---- HTTP helpers ----

    def _get_json(self, path: str, **kwargs) -> Dict:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{self.base_url}{path}", **kwargs)
            resp.raise_for_status()
            return resp.json()

    def _post_json(self, path: str, **kwargs) -> Dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{self.base_url}{path}", **kwargs)
            resp.raise_for_status()
            return resp.json()

    def _delete_json(self, path: str, **kwargs) -> Dict:
        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(f"{self.base_url}{path}", **kwargs)
            resp.raise_for_status()
            return resp.json()
