"""Resource manager (V1.3): CPU / RAM / GPU / VRAM / Disk accounting.

ModelForge runs on developer laptops, so this must never hard-fail when a
measurement is unavailable: every metric is either a real number or explicitly
``None`` with a reason. Admission control uses whatever is measurable and
degrades to a pure instance-count limit otherwise.

GPU/VRAM: inspected through ``torch.cuda`` when the AI stack happens to be
installed. No CUDA call is made otherwise (importing torch for a health check
would cost seconds and megabytes).
"""

from __future__ import annotations

import datetime
import importlib.util
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Rough per-token KV cache allowance used to estimate a loaded model's memory.
_BYTES_PER_CONTEXT_TOKEN = 4096
_WEIGHTS_OVERHEAD = 1.15


def _find_spec(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


@dataclass
class ResourceSnapshot:
    """One point-in-time view of the machine."""

    measured: bool
    cpu_count: int | None = None
    cpu_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_available_bytes: int | None = None
    gpu_available: bool = False
    gpu_name: str | None = None
    vram_total_bytes: int | None = None
    vram_free_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_free_bytes: int | None = None
    notes: list[str] = field(default_factory=list)
    captured_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "cpu_count": self.cpu_count,
            "cpu_percent": self.cpu_percent,
            "memory_total_bytes": self.memory_total_bytes,
            "memory_available_bytes": self.memory_available_bytes,
            "gpu_available": self.gpu_available,
            "gpu_name": self.gpu_name,
            "vram_total_bytes": self.vram_total_bytes,
            "vram_free_bytes": self.vram_free_bytes,
            "disk_total_bytes": self.disk_total_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "notes": self.notes,
            "captured_at": self.captured_at,
        }


class ResourceManager:
    """Measure the machine and account for loaded model instances."""

    def __init__(self, *, data_dir: str | None = None):
        self._lock = threading.RLock()
        self._claims: dict[int, dict] = {}
        self._data_dir = data_dir
        #: Fraction of total RAM the loaded models may claim before eviction.
        self.memory_ratio = 0.85

    # -- measurement --------------------------------------------------------

    def snapshot(self) -> ResourceSnapshot:
        snapshot = ResourceSnapshot(measured=False, captured_at=datetime.datetime.utcnow().isoformat() + "Z")
        snapshot.cpu_count = os.cpu_count()
        if _find_spec("psutil"):
            try:
                import psutil  # type: ignore

                snapshot.cpu_percent = float(psutil.cpu_percent(interval=None))
                memory = psutil.virtual_memory()
                snapshot.memory_total_bytes = int(memory.total)
                snapshot.memory_available_bytes = int(memory.available)
                snapshot.measured = True
            except Exception:
                snapshot.notes.append("psutil present but sampling failed")
        else:
            snapshot.notes.append("psutil not installed: RAM/CPU are reported as unknown")
        self._attach_gpu(snapshot)
        self._attach_disk(snapshot)
        return snapshot

    def _attach_gpu(self, snapshot: ResourceSnapshot) -> None:
        if not _find_spec("torch"):
            snapshot.notes.append("torch not installed: GPU/VRAM are reported as unknown")
            return
        try:
            import torch  # type: ignore

            if not torch.cuda.is_available():
                return
            free, total = torch.cuda.mem_get_info()
            snapshot.gpu_available = True
            snapshot.gpu_name = torch.cuda.get_device_name(0)
            snapshot.vram_total_bytes = int(total)
            snapshot.vram_free_bytes = int(free)
            snapshot.measured = True
        except Exception:
            snapshot.notes.append("CUDA inspection failed")

    def _attach_disk(self, snapshot: ResourceSnapshot) -> None:
        target = self._data_dir or "."
        try:
            usage = shutil.disk_usage(str(Path(target)))
        except OSError:
            snapshot.notes.append("disk usage unavailable")
            return
        snapshot.disk_total_bytes = int(usage.total)
        snapshot.disk_free_bytes = int(usage.free)
        snapshot.measured = True

    # -- per-instance accounting -------------------------------------------

    @staticmethod
    def estimate_instance_bytes(record, context_length: int | None = None) -> int:
        """Estimate the RAM a loaded instance needs (weights + KV cache)."""
        size_bytes = int(getattr(record, "size_bytes", 0) or 0)
        context = int(context_length or 4096)
        weights = int(size_bytes * _WEIGHTS_OVERHEAD)
        kv_cache = context * _BYTES_PER_CONTEXT_TOKEN
        return weights + kv_cache

    def claim(self, model_id: int, *, bytes_estimate: int, context_length: int | None = None) -> dict:
        with self._lock:
            claim = {
                "model_id": model_id,
                "estimated_bytes": int(bytes_estimate),
                "context_length": context_length,
                "claimed_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            self._claims[model_id] = claim
            return dict(claim)

    def release(self, model_id: int) -> None:
        with self._lock:
            self._claims.pop(model_id, None)

    def claims(self) -> list[dict]:
        with self._lock:
            return [dict(claim) for claim in self._claims.values()]

    def claimed_bytes(self) -> int:
        with self._lock:
            return sum(int(claim["estimated_bytes"]) for claim in self._claims.values())

    # -- admission ----------------------------------------------------------

    def memory_budget_bytes(self, snapshot: ResourceSnapshot | None = None) -> int | None:
        snapshot = snapshot or self.snapshot()
        if snapshot.memory_total_bytes is None:
            return None
        return int(snapshot.memory_total_bytes * self.memory_ratio)

    def fits(self, needed_bytes: int, snapshot: ResourceSnapshot | None = None) -> bool | None:
        """Whether ``needed_bytes`` fits the budget.

        ``None`` means "cannot tell" (no measurable RAM) — callers must then use
        the instance-count limit instead of guessing.
        """
        budget = self.memory_budget_bytes(snapshot)
        if budget is None:
            return None
        return self.claimed_bytes() + int(needed_bytes) <= budget

    def status(self) -> dict:
        snapshot = self.snapshot()
        return {
            "resources": snapshot.to_dict(),
            "claimed_bytes": self.claimed_bytes(),
            "memory_budget_bytes": self.memory_budget_bytes(snapshot),
            "instances": self.claims(),
        }


#: Process-wide singleton: the machine has one set of resources.
resource_manager = ResourceManager()


def get_resource_manager() -> ResourceManager:
    return resource_manager


__all__ = [
    "ResourceManager",
    "ResourceSnapshot",
    "get_resource_manager",
    "resource_manager",
]
