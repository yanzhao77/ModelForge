"""Leakage regression tests for chat endpoints (DEV-001)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import httpx
import pytest
from api.chat import _classify_chat_exception
from core.api_contracts import correlation_id
from fastapi.testclient import TestClient


class TestChatErrorClassification:
    """Test that exception classification produces stable, non-leaking errors."""

    def test_classification_httpx_401(self):
        response = httpx.Response(401, request=httpx.Request("POST", "https://api.example.test/v1/responses"))
        exc = httpx.HTTPStatusError("unauthorized", request=response.request, response=response)
        classification = _classify_chat_exception(exc)
        assert classification.code == "AUTHENTICATION_FAILED"
        assert classification.http_status == 403
        assert classification.retryable is False
        # Ensure no sensitive data in message (the message mentions "API Key" which is expected user guidance)
        assert "token" not in classification.message.lower()
        assert "secret" not in classification.message.lower()

    def test_classification_httpx_429(self):
        response = httpx.Response(429, request=httpx.Request("POST", "https://api.example.test/v1/responses"))
        exc = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        classification = _classify_chat_exception(exc)
        assert classification.code == "RATE_LIMITED"
        assert classification.http_status == 429
        assert classification.retryable is True

    def test_classification_httpx_500(self):
        response = httpx.Response(500, request=httpx.Request("POST", "https://api.example.test/v1/responses"))
        exc = httpx.HTTPStatusError("server error", request=response.request, response=response)
        classification = _classify_chat_exception(exc)
        assert classification.code == "PROVIDER_UNAVAILABLE"
        assert classification.http_status == 502
        assert classification.retryable is True

    def test_classification_timeout(self):
        exc = httpx.TimeoutException("timeout", request=httpx.Request("POST", "https://api.example.test/v1/responses"))
        classification = _classify_chat_exception(exc)
        assert classification.code == "REQUEST_TIMEOUT"
        assert classification.http_status == 504
        assert classification.retryable is True

    def test_classification_request_error(self):
        exc = httpx.RequestError("connection failed", request=httpx.Request("POST", "https://api.example.test/v1/responses"))
        classification = _classify_chat_exception(exc)
        assert classification.code == "ENDPOINT_UNREACHABLE"
        assert classification.http_status == 502
        assert classification.retryable is True

    def test_classification_provider_error(self):
        from services.remote_provider_service import RemoteProviderError
        exc = RemoteProviderError("invalid config")
        classification = _classify_chat_exception(exc)
        assert classification.code == "PROVIDER_CONFIG_INVALID"
        assert classification.http_status == 400

    def test_classification_value_error(self):
        exc = ValueError("invalid input")
        classification = _classify_chat_exception(exc)
        assert classification.code == "REQUEST_INVALID"
        assert classification.http_status == 400

    def test_classification_permission_error(self):
        exc = PermissionError("access denied")
        classification = _classify_chat_exception(exc)
        assert classification.code == "MODEL_ACCESS_DENIED"
        assert classification.http_status == 403

    def test_classification_unknown_exception(self):
        exc = RuntimeError("something went wrong")
        classification = _classify_chat_exception(exc)
        assert classification.code == "INFERENCE_FAILED"
        assert classification.http_status == 502


class TestChatNonStreamingLeakage:
    """Test that non-streaming chat endpoint doesn't leak sensitive data."""

    def test_non_streaming_error_has_correlation_header(self, client, monkeypatch):
        """Non-streaming failures must include X-Correlation-ID header."""
        from services.runtime_registry import RuntimeRegistry

        class FailingRuntime:
            async def chat(self, *args, **kwargs):
                raise httpx.HTTPStatusError(
                    "unauthorized",
                    request=httpx.Request("POST", "https://api.example.test/v1/responses"),
                    response=httpx.Response(401, request=httpx.Request("POST", "https://api.example.test/v1/responses")),
                )

        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: FailingRuntime())

        # Register and login
        client.post("/api/v1/auth/register", json={"username": "leaktest1", "password": "testpass", "email": "leak1@test.com"})
        token = client.post("/api/v1/auth/login", json={"username": "leaktest1", "password": "testpass"}).json()["token"]
        r = client.post(
            "/api/v1/chat",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        assert "X-Correlation-ID" in r.headers
        assert len(r.headers["X-Correlation-ID"]) == 32
        # Verify error body has correlation_id matching header
        body = r.json()
        assert "correlation_id" in body["detail"]
        assert body["detail"]["correlation_id"] == r.headers["X-Correlation-ID"]

    def test_non_streaming_error_no_secret_leakage(self, client, monkeypatch):
        """Ensure no API keys, secrets, or paths leak in error responses."""
        from services.runtime_registry import RuntimeRegistry

        class LeakingRuntime:
            async def chat(self, *args, **kwargs):
                # Simulate an exception that contains sensitive data
                raise RuntimeError("Failed to connect to https://api.example.com/v1 with key=sk-12345secret at /home/user/.config")

        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: LeakingRuntime())

        # Register and login
        client.post("/api/v1/auth/register", json={"username": "leaktest2", "password": "testpass", "email": "leak2@test.com"})
        token = client.post("/api/v1/auth/login", json={"username": "leaktest2", "password": "testpass"}).json()["token"]
        r = client.post(
            "/api/v1/chat",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 502
        body = r.json()
        # Check that sensitive data is not in the response
        assert "sk-12345secret" not in body["detail"]["message"]
        assert "https://api.example.com" not in body["detail"]["message"]
        assert "/home/user/.config" not in body["detail"]["message"]
        assert "secret" not in body["detail"]["message"].lower()


class TestChatStreamingLeakage:
    """Test that streaming chat endpoint doesn't leak sensitive data."""

    def test_streaming_error_has_correlation_id(self, client, monkeypatch):
        """Streaming failures must include correlation_id in SSE error event."""
        from services.runtime_registry import RuntimeRegistry

        class FailingRuntime:
            async def stream_chat(self, *args, **kwargs):
                raise httpx.HTTPStatusError(
                    "unauthorized",
                    request=httpx.Request("POST", "https://api.example.test/v1/responses"),
                    response=httpx.Response(401, request=httpx.Request("POST", "https://api.example.test/v1/responses")),
                )
                yield  # pragma: no cover

        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: FailingRuntime())

        # Register and login
        client.post("/api/v1/auth/register", json={"username": "leaktest3", "password": "testpass", "email": "leak3@test.com"})
        token = client.post("/api/v1/auth/login", json={"username": "leaktest3", "password": "testpass"}).json()["token"]
        r = client.post(
            "/api/v1/chat/stream",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        # Check that X-Correlation-ID header is present
        assert "X-Correlation-ID" in r.headers
        # Check SSE error event contains correlation_id
        assert "correlation_id" in r.text

    def test_streaming_error_no_secret_leakage(self, client, monkeypatch):
        """Ensure no sensitive data leaks in streaming error events."""
        from services.runtime_registry import RuntimeRegistry

        class LeakingRuntime:
            async def stream_chat(self, *args, **kwargs):
                raise RuntimeError("Failed to connect to https://api.example.com/v1 with key=sk-12345secret at /home/user/.config")

        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: LeakingRuntime())

        # Register and login
        client.post("/api/v1/auth/register", json={"username": "leaktest4", "password": "testpass", "email": "leak4@test.com"})
        token = client.post("/api/v1/auth/login", json={"username": "leaktest4", "password": "testpass"}).json()["token"]
        r = client.post(
            "/api/v1/chat/stream",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        # Check that sensitive data is not in the response
        assert "sk-12345secret" not in r.text
        assert "https://api.example.com" not in r.text
        assert "/home/user/.config" not in r.text


class TestOpenAICompatibleLeakage:
    """Test that OpenAI compatible endpoint doesn't leak sensitive data."""

    def test_openai_non_stream_error_envelope(self, client, monkeypatch):
        """OpenAI non-streaming errors must use OpenAI error envelope with correlation_id."""
        from services.runtime_registry import RuntimeRegistry

        class FailingRuntime:
            async def chat(self, *args, **kwargs):
                raise RuntimeError("internal error with secret sk-12345")

        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: FailingRuntime())

        # Register and login
        client.post("/api/v1/auth/register", json={"username": "leaktest5", "password": "testpass", "email": "leak5@test.com"})
        token = client.post("/api/v1/auth/login", json={"username": "leaktest5", "password": "testpass"}).json()["token"]
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 500
        body = r.json()
        # OpenAI error envelope
        assert "error" in body
        assert body["error"]["code"] == "INFERENCE_FAILED"
        assert "correlation_id" in body
        # No secret leakage
        assert "sk-12345" not in body["error"]["message"]

    def test_openai_stream_error_envelope(self, client, monkeypatch):
        """OpenAI streaming errors must use OpenAI error envelope with correlation_id."""
        from services.runtime_registry import RuntimeRegistry

        class FailingRuntime:
            async def stream_chat(self, *args, **kwargs):
                raise RuntimeError("internal error with secret sk-12345")
                yield  # pragma: no cover - unreachable but makes this an async generator

        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: FailingRuntime())

        # Register and login
        client.post("/api/v1/auth/register", json={"username": "leaktest6", "password": "testpass", "email": "leak6@test.com"})
        token = client.post("/api/v1/auth/login", json={"username": "leaktest6", "password": "testpass"}).json()["token"]
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}], "stream": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert "X-Correlation-ID" in r.headers
        assert "sk-12345" not in r.text


# Fixture for test client
@pytest.fixture
def client():
    from main import app
    return TestClient(app)