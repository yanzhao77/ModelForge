"""Tests for Ollama provider (DEV-006 coverage)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from runtime.models.base import ModelResult, ToolCall
from runtime.models.ollama import OllamaProvider


class MockAsyncClient:
    """Mock async context manager for httpx.AsyncClient."""
    def __init__(self, mock_response):
        self.mock_response = mock_response
        self.post = AsyncMock(return_value=mock_response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestOllamaProvider:
    """Test Ollama provider with mocked HTTP calls."""

    def test_init_defaults(self):
        """Test provider initialization with defaults."""
        provider = OllamaProvider("test-model")
        assert provider.model_name == "test-model"
        assert provider.base_url == "http://localhost:11434"  # default from settings

    def test_init_custom_base_url(self):
        """Test provider initialization with custom base URL."""
        provider = OllamaProvider("test-model", "http://custom:1234")
        assert provider.base_url == "http://custom:1234"

    def test_init_strips_trailing_slash(self):
        """Test base URL trailing slash is stripped."""
        provider = OllamaProvider("test-model", "http://localhost:11434/")
        assert provider.base_url == "http://localhost:11434"

    def test_capabilities(self):
        """Test capabilities set."""
        provider = OllamaProvider("test-model")
        caps = provider.capabilities()
        assert "CHAT" in caps
        assert "STREAM" in caps
        assert "TOOL_CALLING" in caps

    @pytest.mark.asyncio
    async def test_chat_basic(self):
        """Test basic chat without tools."""
        provider = OllamaProvider("test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello world"},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                tools=None,
            )

        assert isinstance(result, ModelResult)
        assert result.content == "Hello world"
        assert result.model == "test-model"
        assert result.tool_calls == []
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5
        assert result.usage["total_tokens"] == 15

        # Verify call
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:11434/api/chat"
        assert call_args[1]["json"]["model"] == "test-model"
        assert call_args[1]["json"]["messages"] == [{"role": "user", "content": "Hi"}]
        assert call_args[1]["json"]["stream"] is False

    @pytest.mark.asyncio
    async def test_chat_with_tools(self):
        """Test chat with tool calling."""
        provider = OllamaProvider("test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "function": {
                            "name": "get_weather",
                            "arguments": {"location": "New York"},
                        },
                    }
                ],
            },
            "prompt_eval_count": 15,
            "eval_count": 8,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(
                messages=[{"role": "user", "content": "What's the weather?"}],
                tools=tools,
            )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"location": "New York"}
        assert result.tool_calls[0].id == "call_123"

        # Verify tools were passed
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["tools"] == tools

    @pytest.mark.asyncio
    async def test_chat_handles_missing_tool_calls(self):
        """Test chat handles response without tool_calls gracefully."""
        provider = OllamaProvider("test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "No tools here"},
            "prompt_eval_count": 5,
            "eval_count": 3,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                tools=[{"type": "function", "function": {"name": "test", "parameters": {}}}],
            )

        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_chat_raises_on_http_error(self):
        """Test chat raises on HTTP error."""
        provider = OllamaProvider("test-model")

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
            response=httpx.Response(500),
        )

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.chat(messages=[{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_chat_timeout(self):
        """Test chat respects timeout parameter."""
        provider = OllamaProvider("test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Hi"}, "prompt_eval_count": 1, "eval_count": 1}
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_client
            await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                timeout=30.0,
            )
            # Verify timeout was passed to AsyncClient
            mock_client_class.assert_called_once_with(timeout=30.0)

    @pytest.mark.asyncio
    async def test_chat_missing_usage_fields(self):
        """Test chat handles missing usage fields in response."""
        provider = OllamaProvider("test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hi"},
            # Missing prompt_eval_count and eval_count
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

        assert result.usage["prompt_tokens"] == 0
        assert result.usage["completion_tokens"] == 0
        assert result.usage["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_chat_tool_call_without_id(self):
        """Test chat handles tool calls without ID."""
        provider = OllamaProvider("test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "test_tool",
                            "arguments": {"arg": "value"},
                        },
                        # No id field
                    }
                ],
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                tools=[{"type": "function", "function": {"name": "test_tool", "parameters": {}}}],
            )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id.startswith("call_")
        assert result.tool_calls[0].name == "test_tool"
        assert result.tool_calls[0].arguments == {"arg": "value"}