"""Small process-local login limiter for the single-node deployment profile."""
from __future__ import annotations

import time
from collections import deque


class LoginRateLimiter:
    """Apply the same bounded failure window to account and source address.

    Only failures create buckets, and the map is capped: otherwise an
    unauthenticated client could grow process memory by spraying an unbounded
    number of usernames or source addresses.
    """

    DEFAULT_MAX_TRACKED_KEYS = 10_000

    def __init__(
        self,
        attempts: int = 5,
        window_seconds: int = 300,
        max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS,
    ) -> None:
        self.attempts = max(1, attempts)
        self.window_seconds = max(1, window_seconds)
        self.max_tracked_keys = max(1, max_tracked_keys)
        self._failures: dict[str, deque[float]] = {}

    @staticmethod
    def _keys(username: str, client_host: str | None) -> tuple[str, str]:
        return f"account:{username.strip().casefold()}", f"ip:{client_host or 'unknown'}"

    def _recent(self, key: str, now: float) -> deque[float] | None:
        """Trim one bucket in place; unknown or emptied buckets are dropped."""
        bucket = self._failures.get(key)
        if bucket is None:
            return None
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            self._failures.pop(key, None)
            return None
        return bucket

    def allowed(self, username: str, client_host: str | None) -> bool:
        now = time.monotonic()
        return all(
            (bucket := self._recent(key, now)) is None or len(bucket) < self.attempts
            for key in self._keys(username, client_host)
        )

    def record_failure(self, username: str, client_host: str | None) -> None:
        now = time.monotonic()
        self._evict_if_needed(now)
        for key in self._keys(username, client_host):
            bucket = self._recent(key, now)
            if bucket is None:
                bucket = deque()
                self._failures[key] = bucket
            bucket.append(now)

    def record_success(self, username: str, client_host: str | None) -> None:
        for key in self._keys(username, client_host):
            self._failures.pop(key, None)

    def _evict_if_needed(self, now: float) -> None:
        """Keep the failure map bounded: drop stale buckets, then oldest first."""
        if len(self._failures) < self.max_tracked_keys:
            return
        cutoff = now - self.window_seconds
        for key in [k for k, bucket in self._failures.items() if not bucket or bucket[-1] <= cutoff]:
            self._failures.pop(key, None)
        while len(self._failures) >= self.max_tracked_keys:
            self._failures.pop(next(iter(self._failures)), None)


login_rate_limiter = LoginRateLimiter()
