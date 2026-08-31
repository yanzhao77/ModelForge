"""Stable, non-sensitive API error and operation-response helpers."""
from __future__ import annotations

import uuid

from fastapi import HTTPException


def correlation_id() -> str:
    """Create a request-local identifier safe to return to a client."""
    return uuid.uuid4().hex


def problem(status_code: int, code: str, message: str, *, correlation: str | None = None) -> HTTPException:
    """Return a predictable problem detail without exception internals."""
    corr = correlation or correlation_id()
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "correlation_id": corr,
        },
        headers={"X-Correlation-ID": corr},
    )


def operation_result(payload: dict, correlation: str) -> dict:
    """Attach a correlation identifier to a successful mutation response."""
    return {**payload, "correlation_id": correlation}
