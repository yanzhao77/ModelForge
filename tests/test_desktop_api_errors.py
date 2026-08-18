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
