"""Process-wide exclusive leases for scarce local resources.

Model files live in one shared directory that every account may open, but the
machine runs only one inference and one training at a time. A lease records
which account currently owns such a resource. It lives in memory because it
describes live state: a restart releases the lease together with the model or
the training process it stood for.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from core.api_contracts import problem
from fastapi import HTTPException


@dataclass(frozen=True)
class LeaseHolder:
    user_id: int
    username: str


class ResourceBusy(RuntimeError):
    """Raised when another account already owns the requested resource."""

    def __init__(self, lease: "ResourceLease", holder: LeaseHolder):
        super().__init__(f"{lease.kind} is held by {holder.username}")
        self.lease = lease
        self.holder = holder

    def to_problem(self, correlation: str | None = None) -> HTTPException:
        return problem(
            409,
            self.lease.code,
            f"账号 {self.holder.username} 正在使用{self.lease.kind_label}，请等对方停止后再试。",
            correlation=correlation,
        )


@dataclass(frozen=True)
class LeaseHandle:
    lease: "ResourceLease"
    holder: LeaseHolder
    created: bool

    def release(self) -> None:
        self.lease.release(user_id=self.holder.user_id)


class ResourceLease:
    """One-holder-at-a-time lock that stays re-entrant for the owning account."""

    def __init__(self, kind: str, code: str, kind_label: str):
        self.kind = kind
        self.code = code
        self.kind_label = kind_label
        self._lock = threading.Lock()
        self._holder: LeaseHolder | None = None

    def acquire(self, *, user_id: int, username: str) -> LeaseHandle:
        """Claim the resource; raise :class:`ResourceBusy` for another account."""
        with self._lock:
            holder = self._holder
            if holder is not None and holder.user_id != user_id:
                raise ResourceBusy(self, holder)
            created = holder is None
            if created:
                holder = LeaseHolder(user_id=user_id, username=username)
                self._holder = holder
            return LeaseHandle(lease=self, holder=holder, created=created)

    def release(self, *, user_id: int) -> bool:
        with self._lock:
            holder = self._holder
            if holder is None:
                return False
            if holder.user_id != user_id:
                raise ResourceBusy(self, holder)
            self._holder = None
            return True

    def holder(self) -> LeaseHolder | None:
        with self._lock:
            return self._holder


@contextmanager
def transient_hold(lease: ResourceLease, *, user_id: int, username: str) -> Iterator[LeaseHandle]:
    """Hold the resource for one request.

    Only the call that created the lease releases it again, so a model the user
    loaded explicitly survives the individual chat request that used it.
    """
    handle = lease.acquire(user_id=user_id, username=username)
    try:
        yield handle
    finally:
        if handle.created:
            handle.release()


inference_lease = ResourceLease("inference", "RUNTIME_BUSY", "推理服务")
training_lease = ResourceLease("training", "TRAINING_BUSY", "训练资源")


def inference_holder() -> dict | None:
    """Redacted view of the current inference owner for status responses."""
    holder = inference_lease.holder()
    if holder is None:
        return None
    return {"user_id": holder.user_id, "username": holder.username}
