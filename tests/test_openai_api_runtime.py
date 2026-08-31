"""Tests for OpenAI-compatible remote runtime (openai_api_runtime.py)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from services.runtimes.openai_api_runtime import OpenAIRuntime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int = 200, json_data: dict | None = None, url: str = "https://api.example.com/v1/responses"):
    resp = httpx.Response(status_code, json=json_data or {}, request=httpx.Request("POST", url))
    return resp


def _raise_for_status_factory(status_code: int):
    """Return a raise_for_status callable that raises HTTPStatusError."""
    req = httpx.Request("POST", "https://api.example.com/v1/responses")
    resp = httpx.Response(status_code, request=req)

    def _raise():
        raise httpx.HTTPStatusError(f"{status_code} error", request=req, response=resp)

    return _raise


class _MockStreamResponse:
    """Fake httpx streaming response used by _stream_protocol."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self.status_code = status_code
        self._lines = lines
        self.request = httpx.Request("POST", "https://api.example.com/v1/responses")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=self.request,
                response=self,
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _MockStreamClient:
    """Async context manager that supports client.stream(...)."""

    def __init__(self, response: _MockStreamResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **kw):
        return self._response


class _MockAsyncClient:
    """Async context manager for httpx.AsyncClient that supports .post()."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self._call_idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp


# ---------------------------------------------------------------------------
# __init__, _headers, _model, _endpoint
# ---------------------------------------------------------------------------

class TestInitAndProperties:
    def test_init_basic(self):
        rt = OpenAIRuntime("sk-key", "https://api.openai.com/v1", "gpt-4o")
        assert rt.api_key == "sk-key"
        assert rt.base_url == "https://api.openai.com/v1"
        assert rt.default_model == "gpt-4o"
        assert rt.protocol == "responses"

    def test_init_strips_trailing_slash(self):
        rt = OpenAIRuntime("key", "https://api.example.com/v1/", "model", "chat_completions")
        assert rt.base_url == "https://api.example.com/v1"

    def test_init_custom_protocol(self):
        rt = OpenAIRuntime("key", "https://api.example.com/v1", "m", "chat_completions")
        assert rt.protocol == "chat_completions"

    def test_headers_property(self):
        rt = OpenAIRuntime("sk-abc", "https://api.example.com/v1", "m")
        headers = rt._headers
        assert headers["Authorization"] == "Bearer sk-abc"
        assert headers["Content-Type"] == "application/json"

    def test_model_with_name(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "default")
        assert rt._model("custom") == "custom"

    def test_model_falls_back_to_default(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "default")
        assert rt._model("") == "default"
        assert rt._model(None) == "default"  # type: ignore[arg-type]

    def test_model_strips_whitespace(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "default")
        assert rt._model("  gpt-4o  ") == "gpt-4o"

    def test_endpoint_responses(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "m", "responses")
        assert rt._endpoint() == "https://e.com/v1/responses"

    def test_endpoint_chat_completions(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "m", "chat_completions")
        assert rt._endpoint() == "https://e.com/v1/chat/completions"


# ---------------------------------------------------------------------------
# _can_fallback
# ---------------------------------------------------------------------------

class TestCanFallback:
    def _make_exc(self, status_code: int):
        req = httpx.Request("POST", "https://api.example.com/v1/responses")
        resp = httpx.Response(status_code, request=req)
        return httpx.HTTPStatusError(f"{status_code}", request=req, response=resp)

    @pytest.mark.parametrize("code", [404, 405, 501])
    def test_responses_fallback_on_unsupported(self, code):
        exc = self._make_exc(code)
        assert OpenAIRuntime._can_fallback(exc, "responses") is True

    @pytest.mark.parametrize("code", [400, 401, 403, 429, 500, 502, 503])
    def test_responses_no_fallback_on_other(self, code):
        exc = self._make_exc(code)
        assert OpenAIRuntime._can_fallback(exc, "responses") is False

    def test_chat_completions_never_fallback(self):
        exc = self._make_exc(404)
        assert OpenAIRuntime._can_fallback(exc, "chat_completions") is False


# ---------------------------------------------------------------------------
# _responses_text
# ---------------------------------------------------------------------------

class TestResponsesText:
    def test_direct_output_text(self):
        assert OpenAIRuntime._responses_text({"output_text": "hello"}) == "hello"

    def test_direct_output_text_non_string(self):
        assert OpenAIRuntime._responses_text({"output_text": 123}) == ""

    def test_nested_output_array(self):
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hello "},
                        {"type": "output_text", "text": "world"},
                    ],
                }
            ]
        }
        assert OpenAIRuntime._responses_text(payload) == "hello world"

    def test_multiple_output_items(self):
        payload = {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "a"}]},
                {"type": "message", "content": [{"type": "output_text", "text": "b"}]},
            ]
        }
        assert OpenAIRuntime._responses_text(payload) == "ab"

    def test_empty_output(self):
        assert OpenAIRuntime._responses_text({"output": []}) == ""

    def test_missing_output_key(self):
        assert OpenAIRuntime._responses_text({}) == ""

    def test_output_none(self):
        assert OpenAIRuntime._responses_text({"output": None}) == ""

    def test_non_matching_content_type(self):
        payload = {"output": [{"content": [{"type": "other", "text": "x"}]}]}
        assert OpenAIRuntime._responses_text(payload) == ""

    def test_content_text_not_string(self):
        payload = {"output": [{"content": [{"type": "output_text", "text": 123}]}]}
        assert OpenAIRuntime._responses_text(payload) == ""

    def test_item_without_content_key(self):
        payload = {"output": [{"type": "message"}]}
        assert OpenAIRuntime._responses_text(payload) == ""

    def test_content_list_none(self):
        payload = {"output": [{"type": "message", "content": None}]}
        assert OpenAIRuntime._responses_text(payload) == ""


# ---------------------------------------------------------------------------
# load / stop
# ---------------------------------------------------------------------------

class TestLoadStop:
    @pytest.mark.asyncio
    async def test_load(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "gpt-4o")
        result = await rt.load("gpt-4o")
        assert result["status"] == "ready"
        assert result["model"] == "gpt-4o"
        assert result["remote"] is True

    @pytest.mark.asyncio
    async def test_load_default_model(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "gpt-4o")
        result = await rt.load("")
        assert result["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_stop(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "gpt-4o")
        result = await rt.stop("gpt-4o")
        assert result["status"] == "detached"
        assert result["model"] == "gpt-4o"
        assert result["remote"] is True


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------

class TestChat:
    @pytest.mark.asyncio
    async def test_chat_responses_protocol(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        mock_resp = _make_response(200, {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}]
        })
        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockAsyncClient([mock_resp])):
            result = await rt.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert result["content"] == "hi"
        assert result["protocol"] == "responses"
        assert result["remote"] is True

    @pytest.mark.asyncio
    async def test_chat_chat_completions_protocol(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        mock_resp = _make_response(200, {
            "choices": [{"message": {"content": "hello"}}]
        })
        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockAsyncClient([mock_resp])):
            result = await rt.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert result["content"] == "hello"
        assert result["protocol"] == "chat_completions"

    @pytest.mark.asyncio
    async def test_chat_no_model_raises(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "", "responses")
        with pytest.raises(ValueError, match="no selected model"):
            await rt.chat("", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_fallback_on_404(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        req = httpx.Request("POST", "https://api.example.com/v1/responses")
        err_resp = httpx.Response(404, request=req)
        fallback_resp = _make_response(200, {
            "choices": [{"message": {"content": "fallback"}}]
        })
        err_client = _MockAsyncClient([err_resp])
        fallback_client = _MockAsyncClient([fallback_resp])

        call_count = 0

        def client_factory(**kw):
            nonlocal call_count
            clients = [err_client, fallback_client]
            c = clients[call_count]
            call_count += 1
            return c

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=client_factory):
            result = await rt.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert result["content"] == "fallback"
        assert result["protocol"] == "chat_completions"

    @pytest.mark.asyncio
    async def test_chat_fallback_on_405(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        req = httpx.Request("POST", "https://api.example.com/v1/responses")
        err_resp = httpx.Response(405, request=req)
        fallback_resp = _make_response(200, {"choices": [{"message": {"content": "ok"}}]})

        call_count = 0

        def client_factory(**kw):
            nonlocal call_count
            clients = [_MockAsyncClient([err_resp]), _MockAsyncClient([fallback_resp])]
            c = clients[call_count]
            call_count += 1
            return c

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=client_factory):
            result = await rt.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert result["content"] == "ok"

    @pytest.mark.asyncio
    async def test_chat_no_fallback_on_400(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        req = httpx.Request("POST", "https://api.example.com/v1/responses")
        err_resp = httpx.Response(400, request=req)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockAsyncClient([err_resp])):
            with pytest.raises(httpx.HTTPStatusError):
                await rt.chat("gpt-4o", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_no_fallback_on_500(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        req = httpx.Request("POST", "https://api.example.com/v1/responses")
        err_resp = httpx.Response(500, request=req)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockAsyncClient([err_resp])):
            with pytest.raises(httpx.HTTPStatusError):
                await rt.chat("gpt-4o", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# _chat_protocol
# ---------------------------------------------------------------------------

class TestChatProtocol:
    @pytest.mark.asyncio
    async def test_responses_payload(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        msgs = [{"role": "user", "content": "hi"}]
        mock_resp = _make_response(200, {"output_text": "ok"})

        captured = {}

        class CapturingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return mock_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingClient()):
            result = await rt._chat_protocol("responses", "gpt-4o", msgs)

        assert captured["url"] == "https://api.example.com/v1/responses"
        assert captured["json"]["model"] == "gpt-4o"
        assert captured["json"]["input"] == msgs
        assert captured["json"]["stream"] is False
        assert result["content"] == "ok"

    @pytest.mark.asyncio
    async def test_chat_completions_payload(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        msgs = [{"role": "user", "content": "hi"}]
        mock_resp = _make_response(200, {"choices": [{"message": {"content": "ok"}}]})

        captured = {}

        class CapturingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["json"] = json
                return mock_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingClient()):
            result = await rt._chat_protocol("chat_completions", "gpt-4o", msgs)

        assert captured["url"] == "https://api.example.com/v1/chat/completions"
        assert captured["json"]["model"] == "gpt-4o"
        assert captured["json"]["messages"] == msgs
        assert captured["json"]["stream"] is False
        assert result["content"] == "ok"

    @pytest.mark.asyncio
    async def test_responses_temperature_and_max_tokens(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        mock_resp = _make_response(200, {"output_text": "ok"})
        captured = {}

        class CapturingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                captured["json"] = json
                return mock_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingClient()):
            await rt._chat_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}],
                                     temperature=0.7, max_tokens=100)
        assert captured["json"]["temperature"] == 0.7
        assert captured["json"]["max_output_tokens"] == 100

    @pytest.mark.asyncio
    async def test_chat_completions_temperature_and_friends(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        mock_resp = _make_response(200, {"choices": [{"message": {"content": "ok"}}]})
        captured = {}

        class CapturingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                captured["json"] = json
                return mock_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingClient()):
            await rt._chat_protocol("chat_completions", "gpt-4o", [{"role": "user", "content": "hi"}],
                                     temperature=0.5, top_p=0.9, max_tokens=200,
                                     presence_penalty=0.1, frequency_penalty=0.2)
        assert captured["json"]["temperature"] == 0.5
        assert captured["json"]["top_p"] == 0.9
        assert captured["json"]["max_tokens"] == 200
        assert captured["json"]["presence_penalty"] == 0.1
        assert captured["json"]["frequency_penalty"] == 0.2

    @pytest.mark.asyncio
    async def test_responses_none_params_not_sent(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        mock_resp = _make_response(200, {"output_text": "ok"})
        captured = {}

        class CapturingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                captured["json"] = json
                return mock_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingClient()):
            await rt._chat_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}])
        assert "temperature" not in captured["json"]
        assert "max_output_tokens" not in captured["json"]

    @pytest.mark.asyncio
    async def test_chat_completions_empty_choices(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        mock_resp = _make_response(200, {"choices": []})

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockAsyncClient([mock_resp])):
            result = await rt._chat_protocol("chat_completions", "gpt-4o", [{"role": "user", "content": "hi"}])
        assert result["content"] == ""

    @pytest.mark.asyncio
    async def test_chat_completions_missing_choices(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        mock_resp = _make_response(200, {})

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockAsyncClient([mock_resp])):
            result = await rt._chat_protocol("chat_completions", "gpt-4o", [{"role": "user", "content": "hi"}])
        assert result["content"] == ""


# ---------------------------------------------------------------------------
# stream_chat
# ---------------------------------------------------------------------------

class TestStreamChat:
    @pytest.mark.asyncio
    async def test_stream_chat_no_model_raises(self):
        rt = OpenAIRuntime("k", "https://e.com/v1", "", "responses")
        with pytest.raises(ValueError, match="no selected model"):
            async for _ in rt.stream_chat("", [{"role": "user", "content": "hi"}]):
                pass

    @pytest.mark.asyncio
    async def test_stream_chat_responses_protocol(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = [
            'data: {"type":"response.output_text.delta","delta":"hello"}',
            'data: {"type":"response.output_text.delta","delta":" world"}',
            "data: [DONE]",
        ]
        stream_resp = _MockStreamResponse(lines)
        client = _MockStreamClient(stream_resp)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=client):
            chunks = []
            async for chunk in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == ["hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_chat_chat_completions_protocol(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        lines = [
            'data: {"choices":[{"delta":{"content":"hey"}}]}',
            'data: {"choices":[{"delta":{"content":" there"}}]}',
            "data: [DONE]",
        ]
        stream_resp = _MockStreamResponse(lines)
        client = _MockStreamClient(stream_resp)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=client):
            chunks = []
            async for chunk in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == ["hey", " there"]

    @pytest.mark.asyncio
    async def test_stream_chat_fallback_on_404(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")

        err_stream = _MockStreamResponse([], status_code=404)
        ok_lines = ['data: {"choices":[{"delta":{"content":"fb"}}]}', "data: [DONE]"]
        ok_stream = _MockStreamResponse(ok_lines)

        call_count = 0

        def client_factory(**kw):
            nonlocal call_count
            clients = [_MockStreamClient(err_stream), _MockStreamClient(ok_stream)]
            c = clients[call_count]
            call_count += 1
            return c

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=client_factory):
            chunks = []
            async for chunk in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == ["fb"]

    @pytest.mark.asyncio
    async def test_stream_chat_no_fallback_on_400(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        err_stream = _MockStreamResponse([], status_code=400)
        client = _MockStreamClient(err_stream)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=client):
            with pytest.raises(httpx.HTTPStatusError):
                async for _ in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                    pass

    @pytest.mark.asyncio
    async def test_stream_chat_error_event(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ['data: {"type":"error","error":{"message":"rate limited"}}']
        stream_resp = _MockStreamResponse(lines)
        client = _MockStreamClient(stream_resp)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="rate limited"):
                async for _ in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                    pass

    @pytest.mark.asyncio
    async def test_stream_chat_response_failed_event(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ['data: {"type":"response.failed","message":"something broke"}']
        stream_resp = _MockStreamResponse(lines)
        client = _MockStreamClient(stream_resp)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="something broke"):
                async for _ in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                    pass

    @pytest.mark.asyncio
    async def test_stream_chat_response_completed(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = [
            'data: {"type":"response.output_text.delta","delta":"a"}',
            'data: {"type":"response.completed"}',
            'data: {"type":"response.output_text.delta","delta":"b"}',
        ]
        stream_resp = _MockStreamResponse(lines)
        client = _MockStreamClient(stream_resp)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=client):
            chunks = []
            async for chunk in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == ["a"]

    @pytest.mark.asyncio
    async def test_stream_chat_non_data_lines_skipped(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = [
            "",
            ": heartbeat",
            'data: {"type":"response.output_text.delta","delta":"x"}',
            "data: [DONE]",
        ]
        stream_resp = _MockStreamResponse(lines)
        client = _MockStreamClient(stream_resp)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=client):
            chunks = []
            async for chunk in rt.stream_chat("gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == ["x"]


# ---------------------------------------------------------------------------
# _stream_protocol
# ---------------------------------------------------------------------------

class TestStreamProtocol:
    @pytest.mark.asyncio
    async def test_responses_payload_streaming(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ["data: [DONE]"]
        stream_resp = _MockStreamResponse(lines)
        captured = {}

        class CapturingStreamClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None, json=None):
                captured["url"] = url
                captured["json"] = json
                return stream_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingStreamClient()):
            async for _ in rt._stream_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}]):
                pass

        assert captured["url"] == "https://api.example.com/v1/responses"
        assert captured["json"]["model"] == "gpt-4o"
        assert captured["json"]["stream"] is True

    @pytest.mark.asyncio
    async def test_chat_completions_payload_streaming(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        lines = ["data: [DONE]"]
        stream_resp = _MockStreamResponse(lines)
        captured = {}

        class CapturingStreamClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None, json=None):
                captured["url"] = url
                captured["json"] = json
                return stream_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingStreamClient()):
            async for _ in rt._stream_protocol("chat_completions", "gpt-4o", [{"role": "user", "content": "hi"}]):
                pass

        assert captured["url"] == "https://api.example.com/v1/chat/completions"
        assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_json_decode_error_skipped(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ["data: not-valid-json{{", "data: [DONE]"]
        stream_resp = _MockStreamResponse(lines)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockStreamClient(stream_resp)):
            chunks = []
            async for chunk in rt._stream_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_empty_data_line_skipped(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ["data: ", "data: [DONE]"]
        stream_resp = _MockStreamResponse(lines)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockStreamClient(stream_resp)):
            chunks = []
            async for chunk in rt._stream_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_done_stops_iteration(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ["data: [DONE]", 'data: {"type":"response.output_text.delta","delta":"late"}']
        stream_resp = _MockStreamResponse(lines)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockStreamClient(stream_resp)):
            chunks = []
            async for chunk in rt._stream_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_responses_delta_empty_string_skipped(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = [
            'data: {"type":"response.output_text.delta","delta":""}',
            "data: [DONE]",
        ]
        stream_resp = _MockStreamResponse(lines)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockStreamClient(stream_resp)):
            chunks = []
            async for chunk in rt._stream_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_chat_completions_empty_delta_skipped(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        lines = [
            'data: {"choices":[{"delta":{}}]}',
            "data: [DONE]",
        ]
        stream_resp = _MockStreamResponse(lines)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockStreamClient(stream_resp)):
            chunks = []
            async for chunk in rt._stream_protocol("chat_completions", "gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_chat_completions_no_choices_skipped(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        lines = [
            'data: {"choices":[]}',
            'data: {"other":"data"}',
            "data: [DONE]",
        ]
        stream_resp = _MockStreamResponse(lines)

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", return_value=_MockStreamClient(stream_resp)):
            chunks = []
            async for chunk in rt._stream_protocol("chat_completions", "gpt-4o", [{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_responses_temperature_and_max_tokens_streaming(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ["data: [DONE]"]
        stream_resp = _MockStreamResponse(lines)
        captured = {}

        class CapturingStreamClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None, json=None):
                captured["json"] = json
                return stream_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingStreamClient()):
            async for _ in rt._stream_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}],
                                                 temperature=0.8, max_tokens=50):
                pass
        assert captured["json"]["temperature"] == 0.8
        assert captured["json"]["max_output_tokens"] == 50

    @pytest.mark.asyncio
    async def test_chat_completions_temperature_streaming(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "chat_completions")
        lines = ["data: [DONE]"]
        stream_resp = _MockStreamResponse(lines)
        captured = {}

        class CapturingStreamClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None, json=None):
                captured["json"] = json
                return stream_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingStreamClient()):
            async for _ in rt._stream_protocol("chat_completions", "gpt-4o", [{"role": "user", "content": "hi"}],
                                                 temperature=0.5, top_p=0.9, max_tokens=100):
                pass
        assert captured["json"]["temperature"] == 0.5
        assert captured["json"]["top_p"] == 0.9
        assert captured["json"]["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_responses_none_params_not_sent_streaming(self):
        rt = OpenAIRuntime("sk-1", "https://api.example.com/v1", "gpt-4o", "responses")
        lines = ["data: [DONE]"]
        stream_resp = _MockStreamResponse(lines)
        captured = {}

        class CapturingStreamClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None, json=None):
                captured["json"] = json
                return stream_resp

        with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", side_effect=lambda **kw: CapturingStreamClient()):
            async for _ in rt._stream_protocol("responses", "gpt-4o", [{"role": "user", "content": "hi"}]):
                pass
        assert "temperature" not in captured["json"]
        assert "max_output_tokens" not in captured["json"]
