"""Desktop client error-boundary checks for authentication and service failures."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from api_client.client import (
    ApiClientError,
    AuthenticationError,
    AuthorizationError,
    ModelForgeClient,
    ServiceUnavailableError,
)


def response(status, detail):
    request = httpx.Request("GET", "http://qa.local/api/v1/auth/me")
    return httpx.Response(status, json={"detail": detail}, request=request)


@patch("api_client.client.httpx.Client.get")
def test_unauthorized_response_clears_in_memory_session(mock_get):
    mock_get.return_value = response(401, "token expired")
    client = ModelForgeClient("http://qa.local")
    client.set_token("stale-token")
    client.username = "qa-user"

    with pytest.raises(AuthenticationError, match="会话已失效"):
        client.me()

    assert not client.has_token()
    assert client.username is None


def test_stale_unauthorized_response_does_not_clear_new_session():
    client = ModelForgeClient("http://qa.local")
    client.set_token("fresh-token")
    client.username = "qa-user"

    with pytest.raises(ApiClientError, match="STALE_AUTHENTICATION_RESPONSE"):
        client._raise_for_status(response(401, "token expired"), request_token="stale-token")

    assert client.has_token()
    assert client.username == "qa-user"


def test_stale_unauthenticated_response_does_not_clear_new_session():
    client = ModelForgeClient("http://qa.local")
    client.set_token("fresh-token")
    client.username = "qa-user"

    with pytest.raises(ApiClientError, match="STALE_AUTHENTICATION_RESPONSE"):
        client._raise_for_status(response(401, "token missing"), request_token=None)

    assert client.has_token()
    assert client.username == "qa-user"


@pytest.mark.parametrize("code", ["API_KEY_REQUIRED", "API_KEY_INVALID", "API_KEY_REVOKED", "API_KEY_EXPIRED"])
def test_api_key_failure_does_not_invalidate_desktop_login(code):
    client = ModelForgeClient("http://qa.local")
    client.set_token("desktop-token")
    client.username = "qa-user"
    failed = httpx.Response(
        401,
        json={"error": {"code": code, "message": "Invalid API key"}},
        request=httpx.Request("GET", "http://qa.local/v1/models"),
    )

    with pytest.raises(ApiClientError, match=code) as error:
        client._raise_for_status(failed, request_token="desktop-token")

    assert not isinstance(error.value, AuthenticationError)
    assert client.has_token()
    assert client.username == "qa-user"


@patch("api_client.client.httpx.Client.post")
def test_forbidden_response_is_exposed_as_permission_error(mock_post):
    mock_post.return_value = response(403, "operator role required")
    client = ModelForgeClient("http://qa.local")

    with pytest.raises(AuthorizationError, match="无权"):
        client.runtime_start("example-model")


@patch("api_client.client.httpx.Client.get")
def test_network_error_is_mapped_to_service_error(mock_get):
    mock_get.side_effect = httpx.ConnectError("connection refused")
    client = ModelForgeClient("http://qa.local")

    with pytest.raises(ServiceUnavailableError, match="无法连接"):
        client.me()
