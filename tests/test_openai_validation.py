"""Negative tests for OpenAI compatible API (DEV-002)."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from main import app
import services.model_runtime_manager as runtime_module
from services.model_runtime_manager import ModelRuntimeManager


class ValidationEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path

    async def load(self, model_name: str, **kwargs):
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": "hello world"}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "hello "
        yield "world"

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped"}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_token(client, tmp_path, monkeypatch):
    """Register and login a test user, return a local API key."""
    monkeypatch.setenv("MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(
        runtime_module,
        "model_runtime_manager",
        ModelRuntimeManager(runtime_factory=lambda record, path: ValidationEngine(path)),
    )
    username = f"openairegtest-{uuid.uuid4().hex[:8]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "testpass123", "email": f"{username}@test.com"})
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "testpass123"}).json()["token"]
    asset = tmp_path / "mock.gguf"
    asset.write_bytes(b"GGUF-placeholder")
    installed = client.post(
        "/api/v1/models/install",
        json={"name": "mock", "provider": "local", "path": str(asset)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert installed.status_code == 200, installed.text
    issued = client.post("/api/v1/local-api/keys", json={"name": "validation"}, headers={"Authorization": f"Bearer {token}"})
    assert issued.status_code == 200, issued.text
    return issued.json()["secret"]


class TestOpenAIValidation:
    """Test OpenAI-compatible endpoint validation with OpenAI error envelope."""

    def test_empty_messages_rejected(self, client, auth_token):
        """Empty messages array should return 422 with OpenAI error envelope."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": []},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"
        assert "correlation_id" in body
        assert "X-Correlation-ID" in r.headers
        assert "X-Request-ID" in r.headers

    def test_101_messages_rejected(self, client, auth_token):
        """More than 100 messages should return 422."""
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(101)]
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": messages},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_single_message_200001_chars_rejected(self, client, auth_token):
        """Single message exceeding 200000 chars should return 422."""
        long_content = "x" * 200001
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": long_content}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_total_prompt_exceeds_1m_rejected(self, client, auth_token):
        """Total prompt exceeding 1M characters should return 422."""
        # Create multiple messages that sum to > 1M chars
        messages = [{"role": "user", "content": "x" * 200000} for _ in range(6)]  # 1.2M total
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": messages},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"
        assert "1000000" in body["error"]["message"]

    def test_invalid_role_rejected(self, client, auth_token):
        """Invalid role should return 422."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "invalid_role", "content": "test"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_temperature_below_zero_rejected(self, client, auth_token):
        """Temperature < 0 should return 422."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}], "temperature": -0.1},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_temperature_above_two_rejected(self, client, auth_token):
        """Temperature > 2.0 should return 422."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}], "temperature": 2.1},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_max_tokens_below_one_rejected(self, client, auth_token):
        """max_tokens < 1 should return 422."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}], "max_tokens": 0},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_max_tokens_above_32768_rejected(self, client, auth_token):
        """max_tokens > 32768 should return 422."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "test"}], "max_tokens": 32769},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_model_name_empty_rejected(self, client, auth_token):
        """Empty model name should return 422."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "", "messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"

    def test_model_name_too_long_rejected(self, client, auth_token):
        """Model name > 255 chars should return 422."""
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m" * 256, "messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "REQUEST_INVALID"


class TestOpenAIBudgetPrecheck:
    """Test that budget prechecks run before runtime invocation."""

    def test_total_prompt_budget_precheck_non_stream(self, client, auth_token):
        """Total prompt budget exceeded should not call runtime (non-streaming)."""
        from services.runtime_registry import RuntimeRegistry

        mock_runtime = AsyncMock()
        mock_runtime.chat = AsyncMock(return_value={"content": "ok"})

        with patch.object(RuntimeRegistry, "get", return_value=mock_runtime):
            messages = [{"role": "user", "content": "x" * 200000} for _ in range(6)]  # 1.2M total
            r = client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": messages, "stream": False},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 422
            # Runtime should NOT have been called
            mock_runtime.chat.assert_not_called()

    def test_total_prompt_budget_precheck_stream(self, client, auth_token):
        """Total prompt budget exceeded should not call runtime (streaming)."""
        from services.runtime_registry import RuntimeRegistry

        mock_runtime = MagicMock()
        mock_runtime.get = MagicMock(return_value=mock_runtime)
        mock_runtime.stream_chat = AsyncMock()

        with patch.object(RuntimeRegistry, "get", return_value=mock_runtime):
            messages = [{"role": "user", "content": "x" * 200000} for _ in range(6)]  # 1.2M total
            r = client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": messages, "stream": True},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 422
            # Runtime should NOT have been called
            mock_runtime.stream_chat.assert_not_called()

    def test_field_validation_precheck_non_stream(self, client, auth_token):
        """Field validation errors should not call runtime (non-streaming)."""
        from services.runtime_registry import RuntimeRegistry

        mock_runtime = AsyncMock()
        mock_runtime.chat = AsyncMock(return_value={"content": "ok"})

        with patch.object(RuntimeRegistry, "get", return_value=mock_runtime):
            r = client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": [{"role": "invalid", "content": "test"}], "stream": False},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 422
            mock_runtime.chat.assert_not_called()

    def test_field_validation_precheck_stream(self, client, auth_token):
        """Field validation errors should not call runtime (streaming)."""
        from services.runtime_registry import RuntimeRegistry

        mock_runtime = MagicMock()
        mock_runtime.get = MagicMock(return_value=mock_runtime)
        mock_runtime.stream_chat = AsyncMock()

        with patch.object(RuntimeRegistry, "get", return_value=mock_runtime):
            r = client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": [{"role": "invalid", "content": "test"}], "stream": True},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 422
            mock_runtime.stream_chat.assert_not_called()


class TestOpenAISamePrechecks:
    """Test that streaming and non-streaming use the same pre-checks."""

    def test_same_validation_for_stream_and_non_stream(self, client, auth_token):
        """Both streaming and non-streaming should reject invalid role."""
        # Non-streaming
        r1 = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "invalid", "content": "test"}], "stream": False},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        # Streaming
        r2 = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "invalid", "content": "test"}], "stream": True},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r1.status_code == r2.status_code == 422
        assert r1.json()["error"]["code"] == r2.json()["error"]["code"] == "REQUEST_INVALID"

    def test_same_budget_for_stream_and_non_stream(self, client, auth_token):
        """Both streaming and non-streaming should reject total prompt > 1M."""
        messages = [{"role": "user", "content": "x" * 200000} for _ in range(6)]
        # Non-streaming
        r1 = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": messages, "stream": False},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        # Streaming
        r2 = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": messages, "stream": True},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r1.status_code == r2.status_code == 422
        assert r1.json()["error"]["code"] == r2.json()["error"]["code"] == "REQUEST_INVALID"
        # Both should have same correlation_id format
        assert "correlation_id" in r1.json()
        assert "correlation_id" in r2.json()


class TestOpenAIValidRequests:
    """Test that valid requests still work."""

    def test_valid_non_stream_request(self, client, auth_token):
        """Valid non-streaming request should succeed."""
        from services.runtime_registry import RuntimeRegistry

        mock_runtime = AsyncMock()
        mock_runtime.chat = AsyncMock(return_value={"content": "hello world"})

        with patch.object(RuntimeRegistry, "get", return_value=mock_runtime):
            r = client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": [{"role": "user", "content": "hi"}], "stream": False},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["object"] == "chat.completion"
            assert body["choices"][0]["message"]["content"] == "hello world"

    def test_valid_stream_request(self, client, auth_token):
        """Valid streaming request should succeed."""
        from services.runtime_registry import RuntimeRegistry

        async def async_gen():
            yield "hello "
            yield "world"

        mock_runtime = MagicMock()
        mock_runtime.get = MagicMock(return_value=mock_runtime)
        mock_runtime.stream_chat = MagicMock(return_value=async_gen())

        with patch.object(RuntimeRegistry, "get", return_value=mock_runtime):
            r = client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": [{"role": "user", "content": "hi"}], "stream": True},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            assert "hello" in r.text
            assert "world" in r.text
