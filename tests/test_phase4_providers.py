"""Phase 4: Model Provider tests."""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.model_provider import ModelProvider
from services.hf_provider import HFProvider
from services.ms_provider import ModelScopeProvider


class TestProviderInterface:
    """Tests for the abstract provider interface."""

    def test_cannot_instantiate_abstract(self):
        """ModelProvider should not be directly instantiable."""
        with pytest.raises(TypeError):
            ModelProvider()

    def test_concrete_subclass_works(self):
        """A concrete subclass should be instantiable."""

        class DummyProvider(ModelProvider):
            def download(self, model_id, save_dir=None):
                return f"/cache/{model_id}"

            def list_models(self, query="", limit=20):
                return [{"id": "dummy/1"}]

        provider = DummyProvider()
        assert provider.download("test/1") == "/cache/test/1"
        assert len(provider.list_models()) == 1


class TestHFProvider:
    """Tests for HuggingFace provider."""

    def test_init(self):
        provider = HFProvider(cache_dir="/custom/cache")
        assert provider.cache_dir == "/custom/cache"

    @patch("services.hf_provider.snapshot_download")
    def test_download(self, mock_snapshot):
        mock_snapshot.return_value = "/cached/model-path"
        provider = HFProvider(cache_dir="/test/cache")
        path = provider.download("meta-llama/Llama-2-7b")
        assert path == "/cached/model-path"
        mock_snapshot.assert_called_once()

    @patch("services.hf_provider.hf_list_models")
    def test_list_models(self, mock_list):
        mock_model = MagicMock()
        mock_model.modelId = "test/model-1"
        mock_model.author = "tester"
        mock_model.tags = ["nlp"]
        mock_model.downloads = 100
        mock_model.pipeline_tag = "text-generation"
        mock_list.return_value = [mock_model]

        provider = HFProvider()
        results = provider.list_models("nlp", limit=5)
        assert len(results) == 1
        assert results[0]["id"] == "test/model-1"
        assert results[0]["author"] == "tester"


class TestModelScopeProvider:
    """Tests for ModelScope provider."""

    def test_stub_when_no_sdk(self):
        """Should return stub info when SDK is not installed."""
        with patch("services.ms_provider.ModelScopeProvider._snapshot_download", None, create=True):
            provider = ModelScopeProvider.__new__(ModelScopeProvider)
            provider.cache_dir = "/test"
            provider._snapshot_download = None
            results = provider.list_models()
            assert len(results) >= 1
            assert "modelscope-unavailable" in str(results)

    def test_download_raises_without_sdk(self):
        """Should raise RuntimeError when SDK not available."""
        provider = ModelScopeProvider.__new__(ModelScopeProvider)
        provider.cache_dir = "/test"
        provider._snapshot_download = None
        with pytest.raises(RuntimeError, match="ModelScope SDK"):
            provider.download("some/model")
