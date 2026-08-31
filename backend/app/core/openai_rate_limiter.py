"""Per-user concurrency lease, sliding-window rate limiter, and inference timeout.

DEV-007: Public OpenAI-compatible endpoints need resource governance to prevent
abuse, ensure fair usage, and support graceful client disconnect handling.

Design constraints:
- Single-replica only (process-level state, no Redis).
- Lease.release() is idempotent; active count never goes negative.
- Rate-limit check+record is atomic (single lock per user bucket).
- Idle buckets are periodically cleaned to bound memory.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Any

from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lease: admission token held by an active inference request
# ---------------------------------------------------------------------------
class Lease:
    """An admission lease for one inference request.

    The lease holds a reference to the user's bucket and the asyncio.Semaphore
    it acquired.  ``release()`` is idempotent: calling it multiple times will
    only decrement the active counter once and release the semaphore once.
    """

    __slots__ = ("_bucket", "_released")

    def __init__(self, bucket: _UserBucket) -> None:
        self._bucket = bucket
        self._released = False

    def release(self) -> None:
        """Release the concurrency slot.  Idempotent."""
        if self._released:
            return
        self._released = True
        self._bucket.active = max(0, self._bucket.active - 1)
        try:
            self._bucket.semaphore.release()
        except ValueError:
            # Semaphore already at max – should not happen, but be safe.
            pass

    @property
    def is_released(self) -> bool:
        return self._released


# ---------------------------------------------------------------------------
# Per-user bucket: atomic rate-limit + concurrency state
# ---------------------------------------------------------------------------
class _UserBucket:
    """Sliding-window rate limiter + concurrency semaphore for one user."""

    __slots__ = ("semaphore", "timestamps", "active", "max_concurrent", "last_access")

    def __init__(self, max_concurrent: int) -> None:
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.timestamps: deque[float] = deque()
        self.active: int = 0
        self.last_access: float = time.monotonic()


_user_buckets: dict[int, _UserBucket] = defaultdict(
    lambda: _UserBucket(_get_max_concurrent())
)


def _get_max_concurrent() -> int:
    """Read max concurrent from Settings at import time, with safe fallback."""
    try:
        from core.config import settings
        val = int(settings.openai_max_concurrent_per_user)
        return max(1, val)
    except Exception:
        return 4


def _get_rate_limit_window() -> int:
    try:
        from core.config import settings
        val = int(settings.openai_rate_limit_window_seconds)
        return max(1, val)
    except Exception:
        return 60


def _get_rate_limit_max() -> int:
    try:
        from core.config import settings
        val = int(settings.openai_rate_limit_max_requests)
        return max(1, val)
    except Exception:
        return 60


def _get_inference_timeout() -> int:
    try:
        from core.config import settings
        val = int(settings.openai_inference_timeout_seconds)
        return max(1, val)
    except Exception:
        return 120


def _bucket(user_id: int) -> _UserBucket:
    return _user_buckets[user_id]


# ---------------------------------------------------------------------------
# Idle bucket cleanup
# ---------------------------------------------------------------------------
_IDLE_BUCKET_TTL_SECONDS = 300  # 5 minutes


def _cleanup_idle_buckets() -> None:
    """Remove buckets for users with no active requests and idle > TTL."""
    now = time.monotonic()
    stale = [
        uid
        for uid, b in list(_user_buckets.items())
        if b.active == 0 and (now - b.last_access) > _IDLE_BUCKET_TTL_SECONDS
    ]
    for uid in stale:
        del _user_buckets[uid]


# ---------------------------------------------------------------------------
# Rate limit: sliding window with deque
# ---------------------------------------------------------------------------
def _prune_timestamps(bucket: _UserBucket, window: float) -> None:
    cutoff = time.monotonic() - window
    while bucket.timestamps and bucket.timestamps[0] < cutoff:
        bucket.timestamps.popleft()


async def check_and_record_rate_limit(user_id: int) -> JSONResponse | None:
    """Atomically check the rate limit and record the request if allowed.

    Returns a 429 JSONResponse if the user has exceeded the limit, else None.
    """
    window = _get_rate_limit_window()
    max_requests = _get_rate_limit_max()
    bucket = _bucket(user_id)
    bucket.last_access = time.monotonic()

    _prune_timestamps(bucket, window)
    if len(bucket.timestamps) >= max_requests:
        retry_after = int(bucket.timestamps[0] + window - time.monotonic()) + 1
        return JSONResponse(
            {
                "error": {
                    "message": "Rate limit exceeded. Please slow down.",
                    "type": "rate_limit_error",
                    "code": "RATE_LIMITED",
                    "param": None,
                }
            },
            status_code=429,
            headers={"Retry-After": str(max(1, retry_after))},
        )
    bucket.timestamps.append(time.monotonic())
    return None


# ---------------------------------------------------------------------------
# Concurrency: Lease-based admission with timeout
# ---------------------------------------------------------------------------
_ADMISSION_TIMEOUT_SECONDS = 5.0  # max time to wait for a concurrency slot


async def acquire_lease(user_id: int) -> Lease | JSONResponse:
    """Try to acquire a concurrency lease for an inference request.

    Returns a ``Lease`` on success, or a 429 JSONResponse if the admission
    timeout expires (no infinite waiting on the semaphore).
    """
    bucket = _bucket(user_id)
    bucket.last_access = time.monotonic()

    try:
        await asyncio.wait_for(
            bucket.semaphore.acquire(), timeout=_ADMISSION_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return make_concurrency_response(str(user_id))

    bucket.active += 1
    return Lease(bucket)


# ---------------------------------------------------------------------------
# Public helpers (importable by tests and endpoints)
# ---------------------------------------------------------------------------
def active_concurrent(user_id: int) -> int:
    """Return how many inference slots this user currently holds."""
    return _bucket(user_id).active


def rate_limit_window_seconds() -> int:
    return _get_rate_limit_window()


def rate_limit_max_requests() -> int:
    return _get_rate_limit_max()


def inference_timeout_seconds() -> int:
    return _get_inference_timeout()


def make_timeout_response(correlation: str, detail: str = "Inference timed out.") -> JSONResponse:
    """Return a standardized 504 timeout error envelope."""
    return JSONResponse(
        {
            "error": {
                "message": detail,
                "type": "server_error",
                "code": "REQUEST_TIMEOUT",
                "param": None,
            },
            "correlation_id": correlation,
        },
        status_code=504,
    )


def make_concurrency_response(correlation: str) -> JSONResponse:
    """Return a 429 Too Many Requests for concurrency limit."""
    return JSONResponse(
        {
            "error": {
                "message": "Too many concurrent requests for this user.",
                "type": "rate_limit_error",
                "code": "CONCURRENCY_LIMITED",
                "param": None,
            },
            "correlation_id": correlation,
        },
        status_code=429,
        headers={"Retry-After": "1"},
    )


# Periodic idle cleanup – runs at most once per 60 seconds.
_last_cleanup: float = 0.0


def maybe_cleanup_idle() -> None:
    """Trigger idle bucket cleanup if enough time has passed."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup > 60:
        _last_cleanup = now
        _cleanup_idle_buckets()
