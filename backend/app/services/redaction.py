"""Small, dependency-free redaction helpers for persisted summaries and exports."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "cookie",
    "private_key",
    "passphrase",
)
_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|api[_-]?key|token|password|secret|cookie|passphrase)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+\-/=]+")
_PEM_BLOCK = re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL)


def is_sensitive_key(key: object) -> bool:
    """Return whether a JSON field name should never be persisted verbatim."""
    normalized = str(key or "").lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: object, *, max_length: int = 16_384) -> str:
    """Remove common credential shapes from a user-visible diagnostic string."""
    text = str(value or "")
    text = _PEM_BLOCK.sub("[REDACTED_PRIVATE_MATERIAL]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return text[:max_length]


def redact_data(value: Any, *, max_depth: int = 12) -> Any:
    """Recursively redact known-sensitive keys before persistence or export."""
    if max_depth <= 0:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(key) else redact_data(item, max_depth=max_depth - 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_data(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
