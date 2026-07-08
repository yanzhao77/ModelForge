"""Phase 5: Runtime Engine tests."""
import os
import sys
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.runtime import RuntimeEngine
from services.ollama_runtime import OllamaRuntime


class TestRuntimeInterface:
    """Tests for abstract runtime interface."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            RuntimeEngine()

    def test_concrete_subclass_works(self):
        class DummyRuntime(RuntimeEngine):
            async def load(self, model_name, **kwargs):
                return {"status": "loaded", "model": model_name}

            async def chat(self, model_name, messages, **kwargs):
                return {"model": model_name, "content": "hello"}

            async def stop(self, model_name):
                return {"status": "stopped", "model": model_name}

        rt = DummyRuntime()
        assert rt is not None


class TestOllamaRuntime:
    """Tests for Ollama runtime implementation."""

    @pytest.mark.asyncio
    async def test_stop(self):
        rt = OllamaRuntime()
        result = await rt.stop("llama2")
        assert result["status"] == "stopped"
        assert result["model"] == "llama2"

    @pytest.mark.asyncio
    async def test_chat_mocked(self):
        """Chat should send correct payload to Ollama."""
        rt = OllamaRuntime(base_url="http://ollama:9999")
        messages = [{"role": "user", "content": "Hi"}]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "llama2",
            "message": {"role": "assistant", "content": "Hello!"},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await rt.chat("llama2", messages)

        assert result["model"] == "llama2"
        assert result["content"] == "Hello!"
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_when_model_exists(self):
        """Should not pull if model already exists."""
        rt = OllamaRuntime(base_url="http://ollama:9999")

        mock_tags_resp = MagicMock()
        mock_tags_resp.json.return_value = {"models": [{"name": "llama2"}]}
        mock_tags_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_tags_resp
            result = await rt.load("llama2")

        assert result["status"] == "loaded"
        assert result["model"] == "llama2"

    @pytest.mark.asyncio
    async def test_load_pulls_when_missing(self):
        """Should pull model when not in tags."""
        rt = OllamaRuntime(base_url="http://ollama:9999")

        mock_tags_resp = MagicMock()
        mock_tags_resp.json.return_value = {"models": []}
        mock_tags_resp.raise_for_status = MagicMock()

        mock_pull_resp = MagicMock()
        mock_pull_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_get.return_value = mock_tags_resp
            mock_post.return_value = mock_pull_resp
            result = await rt.load("new-model")

        assert result["status"] == "loaded"
        mock_post.assert_called_once()
