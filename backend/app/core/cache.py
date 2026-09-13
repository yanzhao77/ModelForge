"""Small TTL cache with explicit invalidation (V1.9).

The platform caches a few expensive, user-visible computations (embeddings,
retrieval results). A cache without an invalidation story is a correctness bug
waiting to happen, so every entry carries a key namespace and callers must be
able to invalidate it:

* ``invalidate(namespace)`` drops one namespace (e.g. after a new embedding
  model is registered);
* ``invalidate()`` drops everything (e.g. on startup recovery);
* entries expire by TTL even if nobody invalidates them.

Thread-safe and dependency-free: the desktop backend is a single process.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0

    def to_dict(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "invalidations": self.invalidations,
            "hit_rate": round(self.hits / total, 4) if total else None,
        }


class TTLCache:
    """Bounded TTL cache keyed by ``(namespace, key)``."""

    def __init__(self, *, max_entries: int = 512, default_ttl_seconds: float = 300.0):
        self.max_entries = max(1, int(max_entries))
        self.default_ttl_seconds = max(1.0, float(default_ttl_seconds))
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], tuple[float, Any]] = {}
        self.stats = CacheStats()

    @staticmethod
    def make_key(payload: Any) -> str:
        """Stable key for arbitrary JSON-able payloads."""
        try:
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = repr(payload)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:32]

    def get(self, namespace: str, key: str):
        with self._lock:
            entry = self._entries.get((namespace, key))
            if entry is None:
                self.stats.misses += 1
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._entries.pop((namespace, key), None)
                self.stats.misses += 1
                self.stats.evictions += 1
                return None
            self.stats.hits += 1
            return value

    def set(self, namespace: str, key: str, value: Any, *, ttl_seconds: float | None = None) -> None:
        # Sub-second TTLs are allowed on purpose: tests and short-lived
        # retrieval windows both need them.
        ttl = max(0.001, float(ttl_seconds or self.default_ttl_seconds))
        with self._lock:
            if len(self._entries) >= self.max_entries:
                self._evict_locked()
            self._entries[(namespace, key)] = (time.monotonic() + ttl, value)

    def _evict_locked(self) -> None:
        if not self._entries:
            return
        oldest = min(self._entries.items(), key=lambda item: item[1][0])
        self._entries.pop(oldest[0], None)
        self.stats.evictions += 1

    def invalidate(self, namespace: str | None = None) -> int:
        with self._lock:
            if namespace is None:
                removed = len(self._entries)
                self._entries.clear()
            else:
                keys = [key for key in self._entries if key[0] == namespace]
                for key in keys:
                    self._entries.pop(key, None)
                removed = len(keys)
            self.stats.invalidations += 1
            return removed

    def snapshot(self) -> dict:
        with self._lock:
            by_namespace: dict[str, int] = {}
            for namespace, _key in self._entries:
                by_namespace[namespace] = by_namespace.get(namespace, 0) + 1
        return {
            "entries": len(self._entries),
            "max_entries": self.max_entries,
            "by_namespace": by_namespace,
            **self.stats.to_dict(),
        }


#: Process-wide caches. Namespaces keep invalidation targeted.
embedding_cache = TTLCache(max_entries=256, default_ttl_seconds=900)
retrieval_cache = TTLCache(max_entries=256, default_ttl_seconds=120)


def cache_snapshot() -> dict:
    return {
        "embedding": embedding_cache.snapshot(),
        "retrieval": retrieval_cache.snapshot(),
    }


def invalidate_all() -> int:
    return embedding_cache.invalidate() + retrieval_cache.invalidate()


__all__ = [
    "TTLCache",
    "cache_snapshot",
    "embedding_cache",
    "invalidate_all",
    "retrieval_cache",
]
