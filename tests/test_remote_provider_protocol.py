import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from api.chat import _classify_chat_exception
from services.remote_provider_service import RemoteProviderError, normalize_base_url
from services.runtimes.openai_api_runtime import OpenAIRuntime


@pytest.fixture(autouse=True)
def fake_provider_network_validation(monkeypatch):
    """Keep protocol tests independent of the host DNS resolver."""
    monkeypatch.setattr(
        "services.runtimes.openai_api_runtime.validate_provider_target",
        lambda url, mode: "api.example.test",
    )


def test_remote_provider_requires_https_except_loopback():
    assert normalize_base_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"
    assert normalize_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    try:
        normalize_base_url("http://api.example.com/v1")
    except RemoteProviderError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("non-local HTTP must be rejected")


def test_responses_output_text_is_normalized():
    payload = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "hello "},
        {"type": "output_text", "text": "world"},
    ]}]}
    assert OpenAIRuntime._responses_text(payload) == "hello world"


def test_remote_runtime_never_treats_stop_as_provider_side_termination():
    runtime = OpenAIRuntime("secret", "https://api.example.com/v1", "example", "responses")
    assert asyncio.run(runtime.stop("example")) == {"status": "detached", "model": "example", "remote": True}


def test_responses_chat_falls_back_only_when_endpoint_is_unsupported():
    class Response:
        def __init__(self, status_code, payload):
            self.status_code, self._payload = status_code, payload
            self.request = httpx.Request("POST", "https://api.example.test/v1/responses")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("unsupported", request=self.request, response=self)

        def json(self):
            return self._payload

    class Client:
        responses = [Response(404, {}), Response(200, {"choices": [{"message": {"content": "fallback ok"}}]})]
        urls = []

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **_kwargs):
            self.urls.append(url)
            return self.responses.pop(0)

    runtime = OpenAIRuntime("secret", "https://api.example.test/v1", "example", "responses")
    with patch("services.runtimes.openai_api_runtime.httpx.AsyncClient", Client):
        result = asyncio.run(runtime.chat("example", [{"role": "user", "content": "hi"}]))

    assert result["content"] == "fallback ok"
    assert result["protocol"] == "chat_completions"
    assert Client.urls == ["https://api.example.test/v1/responses", "https://api.example.test/v1/chat/completions"]


def test_stream_error_diagnostic_is_safe_and_retry_aware():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.example.test/v1/responses"))
    exc = httpx.HTTPStatusError("limited", request=response.request, response=response)
    classification = _classify_chat_exception(exc)
    detail = classification.to_stream_dict()
    assert detail == {
        "code": "RATE_LIMITED",
        "message": "远程服务正在限流。请稍后由用户手动重试。",
        "retryable": True,
    }
