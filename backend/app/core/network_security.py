"""Default-deny validation of outbound provider targets to prevent SSRF.

MF-SEC-004: a remote-provider URL could previously point at loopback variants,
RFC1918/private space, cloud-metadata (169.254.169.254), IPv6 link-local, or a
hostname whose DNS resolves to an internal address. This module validates a
target before any credential-bearing HTTP request is made.

Policy:
- mode="local"  (desktop/dev): explicit loopback (localhost/127.0.0.1/::1) plus
  public addresses are allowed. All private/link-local/cloud-metadata/devices
  are still forbidden unless allowlisted.
- mode="server" (default): only public addresses are allowed. Loopback and all
  non-public addresses are forbidden unless allowlisted.
- Hostnames are resolved and EVERY resolved address must be public
  (default-deny on mixed resolution). No automatic redirect following should be
  enabled by callers.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "::ffff:127.0.0.1"}
)


class ProviderNetworkError(Exception):
    """Raised when a provider target violates the outbound network policy."""


def provider_validation_mode(environment: str | None) -> str:
    """Map application environments to the provider outbound policy."""
    return "local" if (environment or "development").lower() in {"development", "dev", "test", "testing"} else "server"


def _strip_ipv6_zone(address: str) -> str:
    return address.split("%", 1)[0]


def _normalized_ip(ip: ipaddress._BaseAddress) -> ipaddress._BaseAddress:
    """Return the IPv4 form of an IPv4-mapped IPv6 address for policy checks."""
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


def is_public_ip(address: str) -> bool:
    """Return True only for globally routable addresses.

    ``is_global`` excludes loopback, link-local, private, reserved, multicast,
    broadcast, and unspecified ranges for both address families.
    """
    try:
        ip = ipaddress.ip_address(_strip_ipv6_zone(address))
    except ValueError:
        return False
    ip = _normalized_ip(ip)
    return bool(getattr(ip, "is_global", False))


def is_loopback_host(host: str) -> bool:
    """Return True only for the explicit loopback names/addresses.

    Other 127.0.0.0/8 variants count as loopback-variants and must be blocked
    (default-deny), so they are deliberately not treated as loopback here and
    fall through to the public-address check instead.
    """
    return _strip_ipv6_zone((host or "").strip().lower()) in _LOOPBACK_HOSTS


def _allowlisted(host: str, allowlist: set[str] | None) -> bool:
    if not allowlist:
        return False
    return (_strip_ipv6_zone(host).strip().lower()) in allowlist


def validate_provider_target(
    url: str, mode: str = "server", allowlist: set[str] | None = None
) -> str:
    """Validate a provider base URL; return the validated hostname.

    Raises ProviderNetworkError when the target is disallowed.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip("[]").strip()
    if not host:
        raise ProviderNetworkError("Provider target has no host.")
    port = None
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None and not (0 <= port <= 65535):
        raise ProviderNetworkError("Provider target has an invalid port.")
    allowlist = {h.strip().lower() for h in (allowlist or set()) if h and h.strip()}

    if _allowlisted(host, allowlist):
        return host

    if is_loopback_host(host):
        if mode != "local":
            raise ProviderNetworkError(
                "Loopback provider endpoints are not allowed in server mode."
            )
        return host

    # Literal IP: public only.
    try:
        ip = ipaddress.ip_address(_strip_ipv6_zone(host))
    except ValueError:
        pass
    else:
        ip = _normalized_ip(ip)
        if not getattr(ip, "is_global", False):
            raise ProviderNetworkError("Provider target is not a public address.")
        return host

    # Hostname: resolve and require every resolved address to be public.
    try:
        addrinfo = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ProviderNetworkError("Provider hostname could not be resolved.") from exc
    if not addrinfo:
        raise ProviderNetworkError("Provider hostname resolved to no addresses.")
    resolved: set[str] = set()
    for _family, _stype, _proto, _canon, sockaddr in addrinfo:
        address = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else ""
        if not address:
            continue
        ip = _normalized_ip(ipaddress.ip_address(_strip_ipv6_zone(address)))
        resolved.add(str(ip))
        if not getattr(ip, "is_global", False):
            raise ProviderNetworkError(
                "Provider hostname resolves to a non-public address."
            )
    return host


def resolve_and_validate_host(
    host: str, port: int | None = None, mode: str = "server", allowlist: set[str] | None = None
) -> str:
    """Validate a bare host:port pair using the same policy as validate_provider_target."""
    scheme = "https"
    hostname = (host or "").strip()
    if hostname.startswith("["):
        hostname = hostname.rstrip("]")
    authority = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    if port is not None:
        authority = f"{authority}:{port}"
    return validate_provider_target(f"{scheme}://{authority}", mode=mode, allowlist=allowlist)


def is_allowed_provider_origin(
    url: str, mode: str = "server", allowlist: set[str] | None = None
) -> bool:
    """Non-raising convenience wrapper; True when the target is allowed."""
    try:
        validate_provider_target(url, mode=mode, allowlist=allowlist)
        return True
    except ProviderNetworkError:
        return False
