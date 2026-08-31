"""Tests for OpenAI-compatible provider (DEV-006 coverage)."""
from __future__ import annotations

import json
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
from runtime.models.openai_compatible import OpenAICompatibleProvider


class MockAsyncClient:
    """Mock async context manager for httpx.AsyncClient."""
    def __init__(self, mock_response):
        self.mock_response = mock_response
        self.post = AsyncMock(return_value=mock_response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestOpenAICompatibleProvider:
    """Test OpenAI-compatible provider with mocked HTTP calls."""

    def test_init(self):
        """Test provider initialization."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )
        assert provider.api_key == "test-key"
        assert provider.base_url == "https://api.example.com/v1"
        assert provider.model == "test-model"
        assert provider.protocol == "chat_completions"

    def test_init_strips_trailing_slash(self):
        """Test base URL trailing slash is stripped."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1/",
            model="test-model",
            protocol="chat_completions",
        )
        assert provider.base_url == "https://api.example.com/v1"

    def test_capabilities_chat_completions(self):
        """Test capabilities for chat_completions protocol."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )
        caps = provider.capabilities()
        assert "CHAT" in caps
        assert "TOOL_CALLING" in caps
        assert "STREAM" not in caps  # responses protocol has stream

    def test_capabilities_responses(self):
        """Test capabilities for responses protocol."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="responses",
        )
        caps = provider.capabilities()
        assert "CHAT" in caps
        assert "TOOL_CALLING" in caps

    @pytest.mark.asyncio
    async def test_chat_chat_completions_basic(self):
        """Test basic chat with chat_completions protocol."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Hello world"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
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

        # Verify call
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/chat/completions"
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-key"
        assert call_args[1]["json"]["model"] == "test-model"
        assert call_args[1]["json"]["messages"] == [{"role": "user", "content": "Hi"}]

    @pytest.mark.asyncio
    async def test_chat_responses_basic(self):
        """Test basic chat with responses protocol."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="responses",
        )

        # The responses protocol expects output items with content array containing output_text
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Hello world"},
                    ],
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                tools=None,
            )

        assert result.content == "Hello world"
        assert result.model == "test-model"
        assert result.tool_calls == []
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5

        # Verify endpoint
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/responses"
        assert call_args[1]["json"]["input"] == [{"role": "user", "content": "Hi"}]

    @pytest.mark.asyncio
    async def test_chat_chat_completions_with_tools(self):
        """Test chat with tools in chat_completions protocol."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "New York"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8},
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

    @pytest.mark.asyncio
    async def test_chat_responses_with_tools(self):
        """Test chat with tools in responses protocol."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="responses",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_456",
                    "name": "get_weather",
                    "arguments": '{"location": "London"}',
                }
            ],
            "usage": {"input_tokens": 12, "output_tokens": 6},
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
        assert result.tool_calls[0].arguments == {"location": "London"}
        assert result.tool_calls[0].id == "call_456"

    @pytest.mark.asyncio
    async def test_chat_handles_http_error(self):
        """Test chat raises on HTTP error."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
            response=httpx.Response(500),
        )

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.chat(messages=[{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_chat_handles_missing_usage(self):
        """Test chat handles missing usage fields."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hi"}}],
            # No usage field
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

        assert result.usage["prompt_tokens"] == 0
        assert result.usage["completion_tokens"] == 0
        assert result.usage["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_chat_tool_call_arguments_parsing(self):
        """Test tool call arguments are parsed correctly."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )

        # Test string arguments
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "test",
                                    "arguments": '{"key": "value"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                tools=[{"type": "function", "function": {"name": "test", "parameters": {}}}],
            )

        assert result.tool_calls[0].arguments == {"key": "value"}

    @pytest.mark.asyncio
    async def test_chat_tool_call_invalid_json_arguments(self):
        """Test tool call handles invalid JSON arguments."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "test",
                                    "arguments": "not valid json",
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                tools=[{"type": "function", "function": {"name": "test", "parameters": {}}}],
            )

        assert result.tool_calls[0].arguments == {}

    @pytest.mark.asyncio
    async def test_chat_timeout_parameter(self):
        """Test chat respects timeout parameter."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="chat_completions",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "Hi"}}], "usage": {}}
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_client
            await provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
                timeout=45.0,
            )
            mock_client_class.assert_called_once_with(timeout=45.0, follow_redirects=False)

    @pytest.mark.asyncio
    async def test_chat_responses_handles_missing_output(self):
        """Test responses protocol handles missing output gracefully."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            protocol="responses",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "output": [],
            "usage": {"input_tokens": 5, "output_tokens": 2},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MockAsyncClient(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

        assert result.content == ""
        assert result.tool_calls == []