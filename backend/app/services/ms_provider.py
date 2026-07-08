"""ModelScope model provider implementation.

Uses modelscope SDK when available, with a fallback stub for environments
where it is not installed.
"""
import os
from typing import List, Dict, Optional

from .model_provider import ModelProvider


class ModelScopeProvider(ModelProvider):
    """Provider for downloading models from ModelScope."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".cache", "modelscope")
        self._snapshot_download = None
        try:
            from modelscope.hub.snapshot_download import snapshot_download
            self._snapshot_download = snapshot_download
        except ImportError:
            pass

    def download(self, model_id: str, save_dir: Optional[str] = None) -> str:
        """Download a model from ModelScope."""
        if self._snapshot_download is None:
            raise RuntimeError(
                "ModelScope SDK is not installed. Install with: pip install modelscope"
            )
        target = save_dir or os.path.join(self.cache_dir, "models", model_id.replace("/", "_"))
        os.makedirs(target, exist_ok=True)
        return self._snapshot_download(model_id, cache_dir=target)

    def list_models(self, query: str = "", limit: int = 20) -> List[Dict]:
        """Search models on ModelScope. Returns stub when SDK not available."""
        if self._snapshot_download is None:
            return [{"id": "modelscope-unavailable", "note": "Install modelscope SDK to search"}]

        try:
            from modelscope.hub.api import HubApi
            api = HubApi()
            results = []
            page = api.list_models(query, limit=limit)
            for item in page if isinstance(page, list) else getattr(page, "Models", []):
                results.append({
                    "id": getattr(item, "Id", item.get("Id", "")),
                    "name": getattr(item, "Name", item.get("Name", "")),
                })
            return results
        except Exception:
            return []
