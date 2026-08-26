from __future__ import annotations

import asyncio
import datetime
from collections.abc import Callable
from typing import Any


class Scheduler:
    """In-process asyncio scheduler (spec 38 / 72).

    schedule_once / schedule_interval / cancel. On trigger it CREATES an
    AgentRun through the runtime trigger; the scheduler never executes the
    agent itself (spec 72).
    """

    def __init__(self, trigger: Callable | None = None):
        self._trigger = trigger
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._seq = 0
        self._started = False

    @property
    def trigger(self) -> Callable | None:
        return self._trigger

    @trigger.setter
    def trigger(self, fn: Callable) -> None:
        self._trigger = fn

    def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False
        for job in self._jobs.values():
            if job.get("status") in {"scheduled", "running"}:
                job["status"] = "stopping"
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
        self._tasks.clear()
        for job in self._jobs.values():
            if job.get("status") == "stopping":
                job["status"] = "stopped"

    def _new_id(self, kind: str) -> str:
        self._seq += 1
        return f"{kind}_{self._seq}"

    def schedule_once(self, delay: float, run_spec: dict[str, Any], user_id: int | None = None, callback: Callable | None = None) -> str:
        """Run once after `delay` seconds (spec 38)."""
        job_id = self._new_id("once")
        self._jobs[job_id] = {"type": "once", "delay": delay, "run_spec": run_spec, "user_id": user_id, "status": "scheduled", "triggered_at": None, "last_finished_at": None, "failure_count": 0, "last_error": None, "callback": callback}
        loop = asyncio.get_running_loop()
        self._tasks[job_id] = loop.create_task(self._run_once(job_id, delay, run_spec))
        return job_id

    def schedule_interval(self, interval: float, run_spec: dict[str, Any], user_id: int | None = None, callback: Callable | None = None) -> str:
        """Run every `interval` seconds while started (spec 38 / 39)."""
        job_id = self._new_id("interval")
        self._jobs[job_id] = {"type": "interval", "interval": interval, "run_spec": run_spec, "user_id": user_id, "status": "scheduled", "triggered_at": None, "last_finished_at": None, "failure_count": 0, "last_error": None, "callback": callback}
        loop = asyncio.get_running_loop()
        self._tasks[job_id] = loop.create_task(self._run_interval(job_id, interval, run_spec))
        return job_id

    def cancel(self, job_id: str, user_id: int | None = None) -> bool:
        job = self._jobs.get(job_id)
        if job is None or (user_id is not None and job.get("user_id") != user_id):
            return False
        task = self._tasks.pop(job_id, None)
        if task is None:
            return False
        task.cancel()
        if job_id in self._jobs:
            self._jobs[job_id]["status"] = "cancelled"
        return True

    def jobs(self, user_id: int | None = None) -> list[dict[str, Any]]:
        return [
            {"id": k, **dict(v)} for k, v in self._jobs.items()
            if user_id is None or v.get("user_id") == user_id
        ]

    # ---- internals ----
    async def _run_once(self, job_id: str, delay: float, run_spec: dict[str, Any]) -> None:
        try:
            await asyncio.sleep(delay)
            await self._fire(job_id, run_spec)
        except asyncio.CancelledError:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "cancelled"
        finally:
            self._tasks.pop(job_id, None)

    async def _run_interval(self, job_id: str, interval: float, run_spec: dict[str, Any]) -> None:
        try:
            while self._started:
                await asyncio.sleep(interval)
                if not self._started:
                    break
                await self._fire(job_id, run_spec)
        except asyncio.CancelledError:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "cancelled"
        finally:
            self._tasks.pop(job_id, None)

    async def _fire(self, job_id: str, run_spec: dict[str, Any]) -> None:
        callback = self._jobs.get(job_id, {}).get("callback") or self._trigger
        if callback is None:
            return
        if job_id in self._jobs:
            self._jobs[job_id]["triggered_at"] = datetime.datetime.utcnow().isoformat()
            self._jobs[job_id]["status"] = "running"
        try:
            await callback(run_spec)
        except Exception as exc:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job["failure_count"] = int(job.get("failure_count") or 0) + 1
                job["last_error"] = str(exc)[:500]
                job["status"] = "failed"
            return
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job["last_finished_at"] = datetime.datetime.utcnow().isoformat()
            job["status"] = "completed" if job.get("type") == "once" else "scheduled"
