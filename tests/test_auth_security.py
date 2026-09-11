"""Security regression tests for password hashing and login throttling."""
from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.auth_rate_limit import LoginRateLimiter
from core.security import (
    PBKDF2_SHA256_ITERATIONS,
    hash_password,
    password_needs_rehash,
    verify_password,
)


def test_versioned_password_hash_uses_current_work_factor():
    hashed = hash_password("long-enough-password")
    assert hashed.startswith(f"pbkdf2_sha256${PBKDF2_SHA256_ITERATIONS}$")
    assert verify_password("long-enough-password", hashed)
    assert not verify_password("incorrect-password", hashed)
    assert not password_needs_rehash(hashed)


def test_legacy_password_hash_verifies_and_requests_upgrade():
    salt = "legacy-salt"
    digest = hashlib.pbkdf2_hmac("sha256", b"legacy-password", salt.encode("utf-8"), 100_000).hex()
    legacy = f"{salt}${digest}"
    assert verify_password("legacy-password", legacy)
    assert password_needs_rehash(legacy)


def test_login_rate_limiter_applies_to_account_and_resets_after_success():
    limiter = LoginRateLimiter(attempts=2, window_seconds=60)
    assert limiter.allowed("alice", "127.0.0.1")
    limiter.record_failure("alice", "127.0.0.1")
    limiter.record_failure("alice", "127.0.0.1")
    assert not limiter.allowed("alice", "127.0.0.1")
    limiter.record_success("alice", "127.0.0.1")
    assert limiter.allowed("alice", "127.0.0.1")


def test_login_rate_limiter_does_not_track_checks_without_failures():
    """Simply probing usernames must not allocate permanent state."""
    limiter = LoginRateLimiter(attempts=2, window_seconds=60)

    for index in range(500):
        assert limiter.allowed(f"probe-{index}", "203.0.113.9")

    assert limiter._failures == {}


def test_login_rate_limiter_keeps_memory_bounded_under_username_spraying():
    limiter = LoginRateLimiter(attempts=2, window_seconds=60, max_tracked_keys=50)

    for index in range(500):
        limiter.record_failure(f"probe-{index}", f"203.0.113.{index % 250}")

    # The cap is enforced per recorded failure, and one failure can add the
    # account bucket plus the source bucket.
    assert len(limiter._failures) <= 52
