from __future__ import annotations

from collections import defaultdict
from typing import Any


class MetricsRegistry:
    """In-process runtime metrics (spec 49).

    Single-threaded asyncio process: plain dict counters are sufficient.
    No Prometheus dependency in phase 1.
    """

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._durations: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, amount: int = 1) -> None:
        self._counters[name] += amount

    MAX_DURATION_SAMPLES = 1000

    def record(self, name: str, value: float) -> None:
        samples = self._durations[name]
        samples.append(value)
        if len(samples) > self.MAX_DURATION_SAMPLES:
            # audit P0-3: bound memory growth in long-running processes
            del samples[: len(samples) - self.MAX_DURATION_SAMPLES]

    def count(self, name: str) -> int:
        return self._counters.get(name, 0)

    #: Canonical metric names (spec 49) - always present in snapshots.
    CANONICAL = (
        "agent_runs_total", "agent_runs_success", "agent_runs_failed",
        "agent_run_duration", "tool_calls_total", "tool_call_duration",
        "llm_calls_total", "llm_tokens_total",
    )

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.CANONICAL:
            if name.endswith("_duration"):
                if name not in self._durations:
                    self._durations[name] = []
            elif name not in self._counters:
                self._counters[name] = 0
        for k in sorted(self._counters):
            out[k] = self._counters[k]
        for k in sorted(self._durations):
            vals = self._durations[k]
            out[k] = round(sum(vals), 4)
            out[k + "_total"] = len(vals)
            out[k + "_sum"] = round(sum(vals), 4)
            out[k + "_avg"] = round(sum(vals) / len(vals), 4) if vals else 0.0
            out[k + "_max"] = round(max(vals), 4) if vals else 0.0
        return out

    # --- agent run metrics (spec 49) ---
    def on_run_finished(self, status: str, duration: float) -> None:
        self.inc("agent_runs_total")
        if status in ("COMPLETED",):
            self.inc("agent_runs_success")
        elif status in ("FAILED", "TIMEOUT"):
            self.inc("agent_runs_failed")
        self.record("agent_run_duration", duration)

    def on_tool_call(self, duration: float) -> None:
        self.inc("tool_calls_total")
        self.record("tool_call_duration", duration)

    def on_llm_call(self, tokens: int = 0) -> None:
        self.inc("llm_calls_total")
        self.inc("llm_tokens_total", tokens)