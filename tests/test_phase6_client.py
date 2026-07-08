"""Phase 6: PySide6 Client tests."""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client", "pyside6"))

from api_client.client import ModelForgeClient


class TestModelForgeClient:
    """Tests for the API client."""

    def _mock_get(self, mock_get, return_value):
        mock_resp = MagicMock()
        mock_resp.json.return_value = return_value
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

    def _mock_post(self, mock_post, return_value):
        mock_resp = MagicMock()
        mock_resp.json.return_value = return_value
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

    def _mock_delete(self, mock_delete, return_value):
        mock_resp = MagicMock()
        mock_resp.json.return_value = return_value
        mock_resp.raise_for_status = MagicMock()
        mock_delete.return_value = mock_resp

    @patch("api_client.client.httpx.Client.get")
    def test_get_info(self, mock_get):
        self._mock_get(mock_get, {"name": "ModelForge", "version": "2.0"})
        client = ModelForgeClient("http://localhost:9999")
        info = client.get_info()
        assert info["name"] == "ModelForge"
        assert info["version"] == "2.0"

    @patch("api_client.client.httpx.Client.get")
    def test_list_models_empty(self, mock_get):
        self._mock_get(mock_get, [])
        client = ModelForgeClient()
        models = client.list_models()
        assert models == []

    @patch("api_client.client.httpx.Client.post")
    def test_runtime_chat(self, mock_post):
        self._mock_post(mock_post, {"model": "llama2", "content": "Hello!"})
        client = ModelForgeClient()
        result = client.runtime_chat("llama2", [{"role": "user", "content": "Hi"}])
        assert result["content"] == "Hello!"

    @patch("api_client.client.httpx.Client.post")
    def test_runtime_start(self, mock_post):
        self._mock_post(mock_post, {"status": "loaded", "model": "llama2"})
        client = ModelForgeClient()
        result = client.runtime_start("llama2")
        assert result["status"] == "loaded"

    @patch("api_client.client.httpx.Client.post")
    def test_runtime_stop(self, mock_post):
        self._mock_post(mock_post, {"status": "stopped", "model": "llama2"})
        client = ModelForgeClient()
        result = client.runtime_stop("llama2")
        assert result["status"] == "stopped"

    @patch("api_client.client.httpx.Client.delete")
    def test_remove_model(self, mock_delete):
        self._mock_delete(mock_delete, {"ok": True})
        client = ModelForgeClient()
        result = client.remove_model(42)
        assert result["ok"] is True

    @patch("api_client.client.httpx.Client.get")
    def test_get_info_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        client = ModelForgeClient("http://localhost:19999")
        with pytest.raises(httpx.ConnectError):
            client.get_info()
