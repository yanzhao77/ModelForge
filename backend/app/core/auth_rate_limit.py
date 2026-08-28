"""Small process-local login limiter for the single-node deployment profile."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class LoginRateLimiter:
    """Apply the same bounded failure window to account and source address."""

    def __init__(self, attempts: int = 5, window_seconds: int = 300) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> deque[float]:
        bucket = self._failures[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket

    def allowed(self, username: str, client_host: str | None) -> bool:
        now = time.monotonic()
        keys = (f"account:{username.strip().casefold()}", f"ip:{client_host or 'unknown'}")
        return all(len(self._trim(key, now)) < self.attempts for key in keys)

    def record_failure(self, username: str, client_host: str | None) -> None:
        now = time.monotonic()
        for key in (f"account:{username.strip().casefold()}", f"ip:{client_host or 'unknown'}"):
            self._trim(key, now).append(now)

    def record_success(self, username: str, client_host: str | None) -> None:
        for key in (f"account:{username.strip().casefold()}", f"ip:{client_host or 'unknown'}"):
            self._failures.pop(key, None)


login_rate_limiter = LoginRateLimiter()
