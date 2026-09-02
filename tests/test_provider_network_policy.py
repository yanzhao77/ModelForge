import os
import sys
import tempfile
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from core.network_security import (  # noqa: E402
    ProviderNetworkError,
    is_allowed_provider_origin,
    is_loopback_host,
    is_public_ip,
    resolve_and_validate_host,
    validate_provider_target,
)
from runtime.models.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from services.runtimes.openai_api_runtime import OpenAIRuntime  # noqa: E402

PUBLIC_IP = "93.184.216.34"


def test_is_public_ip_accepts_public_rejects_private():
    assert is_public_ip(PUBLIC_IP)
    assert is_public_ip("8.8.8.8")
    assert not is_public_ip("10.0.0.5")
    assert not is_public_ip("172.16.0.1")
    assert not is_public_ip("192.168.1.10")
    assert not is_public_ip("127.0.0.1")
    assert not is_public_ip("169.254.169.254")
    assert not is_public_ip("0.0.0.0")
    assert not is_public_ip("fe80::1")
    assert not is_public_ip("::1")
    assert not is_public_ip("fc00::1")


def test_public_ip_rejects_malformed_and_mapped_private():
    assert not is_public_ip("not-an-ip")
    assert not is_public_ip("")
    # IPv4-mapped IPv6 of a private address must be rejected.
    assert not is_public_ip("::ffff:192.168.1.1")
    assert is_public_ip("::ffff:93.184.216.34")


def test_is_loopback_host():
    assert is_loopback_host("localhost")
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert not is_loopback_host("127.0.0.2")
    assert not is_loopback_host("example.com")


def test_server_mode_blocks_loopback_and_private_literals():
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://127.0.0.1/v1", mode="server")
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://localhost/v1", mode="server")
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://192.168.1.10/v1", mode="server")
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://169.254.169.254/latest/meta-data/", mode="server")
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://0.0.0.0/v1", mode="server")


def test_local_mode_allows_explicit_loopback_but_blocks_private():
    assert validate_provider_target("https://127.0.0.1/v1", mode="local") == "127.0.0.1"
    assert validate_provider_target("http://localhost:11434/v1", mode="local") == "localhost"
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://192.168.1.10/v1", mode="local")
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://169.254.169.254/", mode="local")


def test_loopback_variants_blocked_even_in_local_mode():
    # 127.0.0.2 is a loopback/variant, not the explicit localhost, so it must
    # be blocked even in local mode (default-deny).
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("http://127.0.0.2:11434/v1", mode="local")
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("http://127.0.0.2:11434/v1", mode="server")


def test_local_mode_allows_ollama_style_loopback():
    # Ollama-style local provider on an arbitrary port must remain usable.
    assert validate_provider_target("http://localhost:11434/v1", mode="local") == "localhost"
    assert validate_provider_target("http://127.0.0.1:8000/v1", mode="local") == "127.0.0.1"


def test_public_literal_allowed():
    assert validate_provider_target(f"https://{PUBLIC_IP}/v1", mode="server") == PUBLIC_IP


def test_allowlist_bypasses_block():
    assert validate_provider_target(
        "https://192.168.1.10/v1", mode="server", allowlist={"192.168.1.10"}
    ) == "192.168.1.10"


@mock.patch("core.network_security.socket.getaddrinfo")
def test_hostname_resolving_to_public_allowed(getaddrinfo):
    getaddrinfo.return_value = [
        (2, 1, 6, "", (PUBLIC_IP, 443)),
    ]
    assert validate_provider_target("https://api.example.test/v1", mode="server") == "api.example.test"


@mock.patch("core.network_security.socket.getaddrinfo")
@pytest.mark.parametrize("resolved_ip", ["127.0.0.1", "10.0.0.3", "169.254.169.254", "192.168.0.1"])
def test_hostname_resolving_to_internal_blocked(getaddrinfo, resolved_ip):
    getaddrinfo.return_value = [(2, 1, 6, "", (resolved_ip, 443))]
    with pytest.raises(ProviderNetworkError, match="resolves to a non-public"):
        validate_provider_target("https://internal.example.test/v1", mode="server")


@mock.patch("core.network_security.socket.getaddrinfo")
def test_mixed_resolution_default_deny(getaddrinfo):
    getaddrinfo.return_value = [
        (2, 1, 6, "", (PUBLIC_IP, 443)),
        (2, 1, 6, "", ("10.0.0.9", 443)),
    ]
    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://mixed.example.test/v1", mode="server")


@mock.patch("core.network_security.socket.getaddrinfo")
def test_unresolvable_hostname_blocked(getaddrinfo):
    getaddrinfo.side_effect = OSError("no address")
    with pytest.raises(ProviderNetworkError, match="could not be resolved"):
        validate_provider_target("https://nonexistent.invalid/v1", mode="server")


@mock.patch("core.network_security.socket.getaddrinfo")
def test_resolve_and_validate_host_uses_same_policy(getaddrinfo):
    getaddrinfo.return_value = [(2, 1, 6, "", (PUBLIC_IP, 443))]
    assert resolve_and_validate_host("api.example.test", 443, mode="server") == "api.example.test"
    getaddrinfo.return_value = [(2, 1, 6, "", ("10.0.0.9", 443))]
    with pytest.raises(ProviderNetworkError):
        resolve_and_validate_host("api.example.test", 443, mode="server")


def test_is_allowed_provider_origin_non_raising():
    assert is_allowed_provider_origin(f"https://{PUBLIC_IP}/v1", mode="server")
    assert not is_allowed_provider_origin("https://127.0.0.1/v1", mode="server")


@pytest.mark.asyncio
async def test_chat_runtime_rejects_target_before_creating_http_client():
    runtime = OpenAIRuntime("secret", "https://127.0.0.2/v1", "model")
    with mock.patch("services.runtimes.openai_api_runtime.httpx.AsyncClient") as client:
        with pytest.raises(ProviderNetworkError):
            await runtime.chat("model", [{"role": "user", "content": "hello"}])
    client.assert_not_called()


@pytest.mark.asyncio
async def test_agent_provider_rejects_target_before_creating_http_client():
    provider = OpenAICompatibleProvider(
        api_key="secret",
        base_url="https://127.0.0.2/v1",
        model="model",
        protocol="responses",
    )
    with mock.patch("runtime.models.openai_compatible.httpx.AsyncClient") as client:
        with pytest.raises(ProviderNetworkError):
            await provider.chat([{"role": "user", "content": "hello"}])
    client.assert_not_called()
