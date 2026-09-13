"""Local model loading and generation must not run on the event loop.

Reading a checkpoint or generating tokens takes minutes. Both used to run
inline inside ``async def`` methods, which froze health checks, task streams and
cancellation for the whole process while a local model was busy.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.runtimes.local_runtime import LocalRuntime  # noqa: E402

BLOCKING_SECONDS = 0.6


@pytest.mark.asyncio
async def test_generation_does_not_block_the_event_loop(monkeypatch):
    runtime = LocalRuntime()
    runtime._model = object()

    def slow_generate(model_name, messages, **kwargs):
        time.sleep(BLOCKING_SECONDS)
        return {"model": model_name, "content": "ok", "raw": None}

    monkeypatch.setattr(runtime, "_chat_sync", slow_generate)

    task = asyncio.create_task(runtime.chat("m", [{"role": "user", "content": "hi"}]))
    started = time.monotonic()
    await asyncio.sleep(0.05)

    assert time.monotonic() - started < BLOCKING_SECONDS / 2
    assert (await task)["content"] == "ok"


@pytest.mark.asyncio
async def test_model_load_does_not_block_the_event_loop(monkeypatch):
    runtime = LocalRuntime()

    def slow_load(model_name, **kwargs):
        time.sleep(BLOCKING_SECONDS)

    monkeypatch.setattr(runtime, "_load_sync", slow_load)

    task = asyncio.create_task(runtime.load("m"))
    started = time.monotonic()
    await asyncio.sleep(0.05)

    assert time.monotonic() - started < BLOCKING_SECONDS / 2
    assert (await task)["status"] == "loaded"


@pytest.mark.asyncio
async def test_stop_does_not_block_the_event_loop(monkeypatch):
    runtime = LocalRuntime()

    def slow_stop():
        time.sleep(BLOCKING_SECONDS)

    monkeypatch.setattr(runtime, "_stop_sync", slow_stop)

    task = asyncio.create_task(runtime.stop("m"))
    started = time.monotonic()
    await asyncio.sleep(0.05)

    assert time.monotonic() - started < BLOCKING_SECONDS / 2
    assert (await task)["status"] == "stopped"
