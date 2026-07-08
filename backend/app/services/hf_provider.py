"""HuggingFace model provider implementation."""
import os
from typing import List, Dict, Optional

from huggingface_hub import HfApi, snapshot_download, list_models as hf_list_models

from .model_provider import ModelProvider


class HFProvider(ModelProvider):
    """Provider for downloading models from HuggingFace Hub."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.api = HfApi()
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")

    def download(self, model_id: str, save_dir: Optional[str] = None) -> str:
        """Download a model snapshot from HuggingFace Hub."""
        target = save_dir or os.path.join(self.cache_dir, "models", model_id.replace("/", "_"))
        os.makedirs(target, exist_ok=True)
        path = snapshot_download(repo_id=model_id, local_dir=target)
        return path

    def list_models(self, query: str = "", limit: int = 20) -> List[Dict]:
        """Search models on HuggingFace Hub."""
        models_iter = hf_list_models(search=query, limit=limit)
        results = []
        for model in models_iter:
            results.append({
                "id": model.modelId if hasattr(model, "modelId") else model.id,
                "author": getattr(model, "author", ""),
                "tags": getattr(model, "tags", []),
                "downloads": getattr(model, "downloads", 0),
                "pipeline_tag": getattr(model, "pipeline_tag", ""),
            })
        return results
