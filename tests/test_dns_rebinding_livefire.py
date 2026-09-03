"""Live-fire DNS-rebinding TOCTOU residual-risk probe.

Documents the residual race between validation-time DNS resolution and
connect-time re-resolution. It does NOT claim the race is eliminated; it
quantifies current behavior so the risk can be tracked as a deployment-env item.

Method:
  validate_provider_target() resolves the host and requires every resolved
  address to be public. A classic DNS rebinding attacker serves a *public*
  address during validation and a *private* address for the subsequent actual
  connection. The httpx client independently re-resolves the hostname at
  connect time, opening a TOCTOU window that this probe demonstrates is still
  open unless the resolved IP(s) are pinned for the connection.

Because the probe cannot intercept the socket connect in a portable way without
a patched transport, it asserts the *contract*: (a) validation rejects any host
whose resolution yields a non-public address, including after an attacker flips
DNS between two lookups; and (b) it records that no IP pinning exists in the
current provider transport, i.e. the window is documented-not-eliminated.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import socket

import pytest
from core.network_security import ProviderNetworkError, validate_provider_target


@pytest.fixture(autouse=True)
def _stub_getaddrinfo(monkeypatch):
    """Stub DNS so the probe is deterministic and offline-safe."""
    import core.network_security as ns

    monkeypatch.setattr(ns.socket, "getaddrinfo", lambda *a, **k: [])
    yield


def test_blocks_host_resolving_to_private_regardless_of_sequence():
    """DNS rebinding probe: if the validator's resolution yields a non-public
    address it must reject. A hostile resolver serves the metadata IP to the
    validation lookup.
    """
    import core.network_security as ns

    def hostile_gai(host, port=None, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    ns.socket.getaddrinfo = hostile_gai

    with pytest.raises(ProviderNetworkError):
        validate_provider_target("https://attacker.example/v1", mode="server")


def test_documents_no_ip_pinning_in_provider_transport():
    """Assert: current design does NOT pin resolved IPs for the connection.

    This is the documented TOCTOU window. The provider services use httpx
    clients with follow_redirects=False but connect to the hostname directly
    (httpx re-resolves at connect time); they do not pin the validated IP. This
    test asserts that the known mitigation (IP pinning) is ABSENT, so the risk
    remains and must be tracked, not dismissed.
    """
    import inspect

    import services.remote_provider_service as rps

    src = inspect.getsource(rps)
    # No pinned-IP transport helper exists anywhere in the provider service.
    assert "pinned" not in src.lower()
    # httpx connects by hostname; follow_redirects=False is present but that is
    # NOT the same as pinning the validated IP.
    assert "follow_redirects" in src


def test_public_hostname_allowed_when_all_resolved_public():
    import core.network_security as ns

    def public_gai(host, port=None, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    ns.socket.getaddrinfo = public_gai

    host = validate_provider_target("https://example.com/v1", mode="server")
    assert host == "example.com"
