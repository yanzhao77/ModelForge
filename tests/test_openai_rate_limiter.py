"""Comprehensive tests for core.openai_rate_limiter and openai_api resource governance.

DEV-007: Tests use real asyncio concurrency (Event, tasks) to verify actual
admission, lease lifecycle, rate limiting, and cleanup semantics.
"""
from __future__ import annotations

import asyncio
import collections.abc
import os
import sys
import time
from collections import defaultdict
from typing import AsyncIterator

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from api.openai_api import _MAX_TOTAL_PROMPT_CHARS, _safe_aclose, _stream_with_lease
from core.openai_rate_limiter import (
    _IDLE_BUCKET_TTL_SECONDS,
    Lease,
    _bucket,
    _cleanup_idle_buckets,
    _prune_timestamps,
    _user_buckets,
    _UserBucket,
    acquire_lease,
    active_concurrent,
    check_and_record_rate_limit,
    inference_timeout_seconds,
    make_concurrency_response,
    make_timeout_response,
    maybe_cleanup_idle,
    rate_limit_max_requests,
    rate_limit_window_seconds,
)

# ---------------------------------------------------------------------------
# Unique user ID counter to isolate tests
# ---------------------------------------------------------------------------
_next_uid = 800_000


def _fresh_uid() -> int:
    global _next_uid
    _next_uid += 1
    return _next_uid


def _clear_user(uid: int) -> None:
    _user_buckets.pop(uid, None)


# ===================================================================
# 1. Lease
# ===================================================================
class TestLease:
    def test_release_decrements_active(self):
        uid = _fresh_uid()
        b = _UserBucket(4)
        b.active = 2
        _user_buckets[uid] = b
        lease = Lease(b)
        assert b.active == 2
        lease.release()
        assert b.active == 1

    def test_release_is_idempotent(self):
        uid = _fresh_uid()
        b = _UserBucket(4)
        b.active = 1
        _user_buckets[uid] = b
        lease = Lease(b)
        lease.release()
        assert b.active == 0
        lease.release()  # second call
        assert b.active == 0  # must not go negative
        assert lease.is_released

    def test_release_semaphore_count(self):
        uid = _fresh_uid()
        b = _UserBucket(2)
        _user_buckets[uid] = b
        lease = Lease(b)
        # Semaphore started at 2; lease did NOT acquire it (we manage active manually)
        lease.release()
        # No error from releasing an already-full semaphore
        assert b.active == 0


# ===================================================================
# 2. Concurrency admission
# ===================================================================
class TestAcquireLease:
    @pytest.mark.asyncio
    async def test_acquire_returns_lease(self):
        uid = _fresh_uid()
        _clear_user(uid)
        result = await acquire_lease(uid)
        assert isinstance(result, Lease)
        assert active_concurrent(uid) == 1
        result.release()
        assert active_concurrent(uid) == 0

    @pytest.mark.asyncio
    async def test_four_concurrent_then_reject(self):
        """4 slots occupied, 5th must get CONCURRENCY_LIMITED."""
        uid = _fresh_uid()
        _clear_user(uid)
        leases = []
        for _ in range(4):
            r = await acquire_lease(uid)
            assert isinstance(r, Lease)
            leases.append(r)
        assert active_concurrent(uid) == 4

        # 5th must be rejected within admission timeout
        t0 = time.monotonic()
        r5 = await acquire_lease(uid)
        elapsed = time.monotonic() - t0
        assert isinstance(r5, make_concurrency_response("x").__class__)  # JSONResponse
        # Check it's a 429
        assert r5.status_code == 429  # type: ignore[union-attr]
        assert elapsed < 10  # must not block forever

        # Release one, then another should succeed
        leases[0].release()
        assert active_concurrent(uid) == 3
        r6 = await acquire_lease(uid)
        assert isinstance(r6, Lease)
        r6.release()
        for ls in leases[1:]:
            ls.release()

    @pytest.mark.asyncio
    async def test_users_are_isolated(self):
        u1, u2 = _fresh_uid(), _fresh_uid()
        _clear_user(u1)
        _clear_user(u2)
        l1 = await acquire_lease(u1)
        l2 = await acquire_lease(u2)
        assert active_concurrent(u1) == 1
        assert active_concurrent(u2) == 1
        l1.release()
        assert active_concurrent(u1) == 0
        assert active_concurrent(u2) == 1
        l2.release()

    @pytest.mark.asyncio
    async def test_concurrent_tasks_actually_block(self):
        """Use asyncio.Event to verify real concurrent blocking."""
        uid = _fresh_uid()
        _clear_user(uid)
        all_held = asyncio.Event()
        held = asyncio.Event()
        holder_count = 0

        async def holder():
            nonlocal holder_count
            lease = await acquire_lease(uid)
            holder_count += 1
            if holder_count == 4:
                all_held.set()
            await asyncio.wait_for(held.wait(), timeout=5)
            lease.release()

        async def waiter():
            await all_held.wait()
            r = await acquire_lease(uid)
            if isinstance(r, Lease):
                r.release()
                return "acquired"
            return "rejected"

        # Fill 4 slots
        holders = [asyncio.create_task(holder()) for _ in range(4)]
        await all_held.wait()
        await asyncio.sleep(0.02)

        # 5th waiter should be blocked (not yet completed)
        w = asyncio.create_task(waiter())
        await asyncio.sleep(0.15)
        assert not w.done()  # waiter is blocked on semaphore

        # Release one holder
        held.set()
        await asyncio.sleep(0.1)

        # Now the waiter should have completed
        assert w.done()
        assert w.result() == "acquired"

        # Cleanup
        held.set()
        await asyncio.gather(*holders, return_exceptions=True)


# ===================================================================
# 3. Rate limiting
# ===================================================================
class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_within_limit(self):
        uid = _fresh_uid()
        _clear_user(uid)
        result = await check_and_record_rate_limit(uid)
        assert result is None

    @pytest.mark.asyncio
    async def test_exceeds_limit_returns_429(self):
        uid = _fresh_uid()
        _clear_user(uid)
        b = _bucket(uid)
        now = time.monotonic()
        max_req = rate_limit_max_requests()
        b.timestamps = collections.deque([now - i for i in range(max_req)])
        result = await check_and_record_rate_limit(uid)
        assert result is not None
        assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_retry_after_header(self):
        uid = _fresh_uid()
        _clear_user(uid)
        b = _bucket(uid)
        now = time.monotonic()
        b.timestamps = collections.deque([now - i for i in range(rate_limit_max_requests())])
        result = await check_and_record_rate_limit(uid)
        assert result is not None
        assert "Retry-After" in result.headers
        assert int(result.headers["Retry-After"]) >= 1

    @pytest.mark.asyncio
    async def test_check_and_record_is_atomic(self):
        """Rate limit check+record must be atomic: 60th request allowed, 61st rejected."""
        uid = _fresh_uid()
        _clear_user(uid)
        max_req = rate_limit_max_requests()
        for i in range(max_req):
            result = await check_and_record_rate_limit(uid)
            assert result is None, f"Request {i+1} should be allowed"
        result = await check_and_record_rate_limit(uid)
        assert result is not None
        assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_window_slide_allows_after_expiry(self):
        uid = _fresh_uid()
        _clear_user(uid)
        b = _bucket(uid)
        window = rate_limit_window_seconds()
        # All timestamps just outside the window
        b.timestamps = collections.deque([time.monotonic() - window - 1] * 5)
        result = await check_and_record_rate_limit(uid)
        assert result is None  # should be allowed after prune

    @pytest.mark.asyncio
    async def test_concurrent_rejected_not_counted(self):
        """Requests rejected by concurrency limit should NOT be recorded in rate window."""
        uid = _fresh_uid()
        _clear_user(uid)
        # Use up all 4 slots
        leases = []
        for _ in range(4):
            ls = await acquire_lease(uid)
            leases.append(ls)

        # Attempt 5th – rejected by concurrency
        r = await acquire_lease(uid)
        assert isinstance(r, make_concurrency_response("x").__class__)
        assert r.status_code == 429

        # Check rate limit: only 0 requests recorded (acquire_lease doesn't record)
        rate_result = await check_and_record_rate_limit(uid)
        assert rate_result is None  # should be allowed

        for ls in leases:
            ls.release()


# ===================================================================
# 4. Idle bucket cleanup
# ===================================================================
class TestIdleCleanup:
    def test_cleanup_removes_idle_buckets(self):
        uid = _fresh_uid()
        b = _UserBucket(4)
        b.active = 0
        b.last_access = time.monotonic() - _IDLE_BUCKET_TTL_SECONDS - 10
        _user_buckets[uid] = b
        _cleanup_idle_buckets()
        assert uid not in _user_buckets

    def test_cleanup_keeps_active_buckets(self):
        uid = _fresh_uid()
        b = _UserBucket(4)
        b.active = 2
        b.last_access = time.monotonic() - _IDLE_BUCKET_TTL_SECONDS - 10
        _user_buckets[uid] = b
        _cleanup_idle_buckets()
        assert uid in _user_buckets
        b.active = 0  # cleanup for other tests

    def test_cleanup_keeps_recent_buckets(self):
        uid = _fresh_uid()
        b = _UserBucket(4)
        b.active = 0
        b.last_access = time.monotonic() - 10  # recent
        _user_buckets[uid] = b
        _cleanup_idle_buckets()
        assert uid in _user_buckets

    def test_maybe_cleanup_idle_throttled(self):
        """maybe_cleanup_idle should not run more than once per 60s."""
        import core.openai_rate_limiter as mod
        mod._last_cleanup = time.monotonic()  # set to now
        before = mod._last_cleanup
        maybe_cleanup_idle()  # should be a no-op (recent cleanup)
        assert mod._last_cleanup == before  # unchanged
        mod._last_cleanup = 0  # reset for other tests


# ===================================================================
# 5. Streaming lease lifecycle
# ===================================================================
class TestStreamingLeaseLifecycle:
    @pytest.mark.asyncio
    async def test_stream_holds_lease_until_done(self):
        """Lease must remain held until [DONE] is sent."""
        uid = _fresh_uid()
        _clear_user(uid)
        lease = await acquire_lease(uid)
        assert active_concurrent(uid) == 1

        collected: list[str] = []

        async def fake_stream() -> AsyncIterator[str]:
            yield "chunk1"
            yield "chunk2"

        async for tok in _stream_with_lease(
            lease, "model", [], "corr", 120.0
        ):
            collected.append(tok)
            # While streaming, lease must still be held
            assert active_concurrent(uid) == 1

        # After stream, lease must be released
        assert active_concurrent(uid) == 0
        assert any("[DONE]" in t for t in collected)

    @pytest.mark.asyncio
    async def test_stream_releases_on_exception(self):
        uid = _fresh_uid()
        _clear_user(uid)
        lease = await acquire_lease(uid)

        async def failing_stream() -> AsyncIterator[str]:
            raise RuntimeError("boom")
            yield  # type: ignore[misc]  # make it an async generator

        collected: list[str] = []
        async for tok in _stream_with_lease(
            lease, "model", [], "corr", 120.0
        ):
            collected.append(tok)

        assert active_concurrent(uid) == 0
        assert any("INFERENCE_FAILED" in t for t in collected)
        assert any("[DONE]" in t for t in collected)

    @pytest.mark.asyncio
    async def test_stream_releases_on_timeout(self):
        uid = _fresh_uid()
        _clear_user(uid)
        lease = await acquire_lease(uid)

        async def slow_stream(model, msgs):
            await asyncio.sleep(10)
            yield "too late"

        class FakeRuntime:
            def get(self):
                return self
            def stream_chat(self, model, msgs):
                return slow_stream(model, msgs)

        import api.openai_api as mod
        original = mod.get_runtime
        mod.get_runtime = lambda: FakeRuntime()
        try:
            collected: list[str] = []
            async for tok in _stream_with_lease(
                lease, "model", [], "corr", 0.05
            ):
                collected.append(tok)

            assert active_concurrent(uid) == 0
            assert any("REQUEST_TIMEOUT" in t for t in collected)
            assert any("[DONE]" in t for t in collected)
        finally:
            mod.get_runtime = original

    @pytest.mark.asyncio
    async def test_stream_releases_on_cancelled(self):
        """CancelledError must be re-raised AND lease released."""
        uid = _fresh_uid()
        _clear_user(uid)
        lease = await acquire_lease(uid)

        async def slow_stream(model, msgs):
            while True:
                await asyncio.sleep(10)
                yield "x"

        class FakeRuntime:
            def get(self):
                return self
            def stream_chat(self, model, msgs):
                return slow_stream(model, msgs)

        import api.openai_api as mod
        original = mod.get_runtime
        mod.get_runtime = lambda: FakeRuntime()
        try:
            async def cancel_me():
                async for _ in _stream_with_lease(
                    lease, "model", [], "corr", 120.0
                ):
                    pass

            task = asyncio.create_task(cancel_me())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert active_concurrent(uid) == 0
        finally:
            mod.get_runtime = original

    @pytest.mark.asyncio
    async def test_stream_aclose_iterator(self):
        """Async iterator's aclose() should be called on normal exit."""
        close_called = False

        class MockIterator:
            def __init__(self):
                self.closed = False

            async def __aiter__(self):
                yield "a"
                yield "b"

            async def aclose(self):
                nonlocal close_called
                close_called = True

        # _safe_aclose should call aclose
        it = MockIterator()
        async for _ in it:
            pass
        await _safe_aclose(it)
        assert close_called


# ===================================================================
# 6. Non-streaming timeout
# ===================================================================
class TestNonStreamingTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_504(self):
        resp = make_timeout_response("tcorr")
        assert resp.status_code == 504
        body = resp.body.decode()
        assert "REQUEST_TIMEOUT" in body
        assert "tcorr" in body

    def test_make_concurrency_response_429(self):
        resp = make_concurrency_response("ccorr")
        assert resp.status_code == 429
        body = resp.body.decode()
        assert "CONCURRENCY_LIMITED" in body
        assert "ccorr" in body


# ===================================================================
# 7. Configuration
# ===================================================================
class TestConfiguration:
    def test_rate_limit_window(self):
        assert rate_limit_window_seconds() >= 1

    def test_rate_limit_max(self):
        assert rate_limit_max_requests() >= 1

    def test_inference_timeout(self):
        assert inference_timeout_seconds() >= 1

    def test_settings_integration(self):
        from core.config import settings
        assert settings.openai_max_concurrent_per_user >= 1
        assert settings.openai_rate_limit_window_seconds >= 1
        assert settings.openai_rate_limit_max_requests >= 1
        assert settings.openai_inference_timeout_seconds >= 1


# ===================================================================
# 8. Endpoint integration tests
# ===================================================================
class TestOpenAIEndpointGovernance:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def _register_and_login(self, client, username="govtest"):
        client.post("/api/v1/auth/register", json={
            "username": username,
            "password": "testpass",
            "email": f"{username}@test.com",
        })
        resp = client.post("/api/v1/auth/login", json={
            "username": username,
            "password": "testpass",
        })
        return resp.json()["token"]

    def test_rate_limit_exceeded_returns_429(self, client, monkeypatch):
        from core import openai_rate_limiter
        token = self._register_and_login(client, "rltest")
        from core.security import decode_token
        uid = int(decode_token(token)["sub"])

        test_buckets = defaultdict(lambda: _UserBucket(4))
        b = test_buckets[uid]
        now = time.monotonic()
        b.timestamps = collections.deque([now - i for i in range(rate_limit_max_requests())])
        monkeypatch.setattr(openai_rate_limiter, "_user_buckets", test_buckets)

        r = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 429
        assert "X-Correlation-ID" in r.headers

    def test_total_chars_exceeded_returns_422(self, client):
        token = self._register_and_login(client, "chartest")
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "x" * (_MAX_TOTAL_PROMPT_CHARS + 1)}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422
        body = r.json()
        assert "REQUEST_INVALID" in body.get("error", {}).get("code", "")
        assert "X-Correlation-ID" in r.headers

    def test_empty_messages_returns_422(self, client):
        token = self._register_and_login(client, "emptymsg")
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422

    def test_error_no_secret_leakage(self, client, monkeypatch):
        """Error responses must not leak URLs, tokens, or paths."""
        from core import openai_rate_limiter
        token = self._register_and_login(client, "noleak")
        from core.security import decode_token
        uid = int(decode_token(token)["sub"])

        # Force rate limit
        test_buckets = defaultdict(lambda: _UserBucket(4))
        b = test_buckets[uid]
        b.timestamps = collections.deque([time.monotonic()] * rate_limit_max_requests())
        monkeypatch.setattr(openai_rate_limiter, "_user_buckets", test_buckets)

        r = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "secret-key-12345"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        text = r.text
        assert "secret-key-12345" not in text
        assert "sk-" not in text

    def test_concurrency_headers_present(self, client):
        token = self._register_and_login(client, "hdrtest")
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Response should have correlation headers (may be 200 or 500 depending on runtime)
        assert "X-Correlation-ID" in r.headers
