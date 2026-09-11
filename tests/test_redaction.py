"""Credential redaction for persisted diagnostics, events and exports."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.redaction import redact_data, redact_text  # noqa: E402


@pytest.mark.parametrize("secret", [
    "sk-proj-AbCd1234EfGh5678IjKl",                       # OpenAI style
    "hf_AbCdEfGhIjKlMnOpQrStUvWxYz123456",               # Hugging Face
    "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz123456",              # GitHub classic
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz012345",  # GitHub PAT
    "AKIAIOSFODNN7EXAMPLE",                               # AWS access key id
    # Assembled at runtime: a literal would trip GitHub push protection.
    "xoxb-" + "123456789012-abcdefghijklmnop",            # Slack
    "AIzaSyA1234567890abcdefghijklmnopqrstuv",            # Google API key
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc123signature",  # JWT
])
def test_bare_credentials_are_redacted(secret):
    """Upstream errors embed credentials without a field name."""
    redacted = redact_text(f"upstream error: {secret}")

    assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_quoted_json_values_are_redacted():
    payload = (
        '{"api_key": "abcd1234", "access_token": '
        '"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc123signature"}'
    )

    redacted = redact_text(payload)

    assert "abcd1234" not in redacted
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert '"api_key": "[REDACTED]"' in redacted


def test_redact_data_covers_nested_payloads_and_keeps_plain_fields():
    payload = {
        "provider": {"api_key": "abcd1234", "base_url": "https://example.test/v1"},
        "trace": ["retry after sk-proj-AbCd1234EfGh5678IjKl"],
        "duration_seconds": 12,
    }

    safe = redact_data(payload)

    assert safe["provider"]["api_key"] == "[REDACTED]"
    assert safe["provider"]["base_url"] == "https://example.test/v1"
    assert safe["duration_seconds"] == 12
    assert "sk-proj" not in str(safe)


def test_ordinary_diagnostics_are_left_alone():
    text = "download finished in 12s · model owner_repo/model.gguf"

    assert redact_text(text) == text
