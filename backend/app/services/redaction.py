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
    # JSON bodies quote the key ("api_key": "..."), so quotes are tolerated on
    # both sides of the separator.
    r"(?i)\b(authorization|api[_-]?key|token|password|secret|cookie|passphrase)\b"
    r"(['\"]?\s*[:=]\s*['\"]?)([^\s,;'\"]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+\-/=]+")
_PEM_BLOCK = re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL)
# Provider credentials that appear without a field name, for example inside an
# upstream error such as "Incorrect API key provided: sk-proj-...".
_CREDENTIAL_SHAPES = re.compile(
    r"(?i)("
    r"sk-[a-z0-9_-]{16,}"           # OpenAI / Anthropic style
    r"|hf_[a-z0-9]{20,}"            # Hugging Face
    r"|github_pat_[a-z0-9_]{20,}"   # GitHub fine-grained PAT
    r"|gh[pousr]_[a-z0-9]{20,}"     # GitHub classic tokens
    r"|xox[abprs]-[a-z0-9-]{10,}"   # Slack
    r"|AKIA[0-9A-Z]{16}"            # AWS access key id
    r"|AIza[0-9A-Za-z_-]{35}"       # Google API key
    r"|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"  # JWT
    r")"
)


def is_sensitive_key(key: object) -> bool:
    """Return whether a JSON field name should never be persisted verbatim."""
    normalized = str(key or "").lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: object, *, max_length: int = 16_384) -> str:
    """Remove common credential shapes from a user-visible diagnostic string."""
    text = str(value or "")
    text = _PEM_BLOCK.sub("[REDACTED_PRIVATE_MATERIAL]", text)
    text = _CREDENTIAL_SHAPES.sub("[REDACTED]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    return text[:max_length]


def redact_data(value: Any, *, max_depth: int = 12, max_text_length: int = 16_384) -> Any:
    """Recursively redact known-sensitive keys before persistence or export."""
    if max_depth <= 0:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(key) else redact_data(item, max_depth=max_depth - 1, max_text_length=max_text_length)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_data(item, max_depth=max_depth - 1, max_text_length=max_text_length) for item in value]
    if isinstance(value, str):
        return redact_text(value, max_length=max_text_length)
    return value
