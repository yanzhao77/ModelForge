"""Stable, non-sensitive API error and operation-response helpers."""
from __future__ import annotations

import uuid

from fastapi import HTTPException


def correlation_id() -> str:
    """Create a request-local identifier safe to return to a client."""
    return uuid.uuid4().hex


def problem(
    status_code: int,
    code: str,
    message: str,
    *,
    correlation: str | None = None,
    details: dict | None = None,
) -> HTTPException:
    """Return a predictable problem detail without exception internals.

    ``details`` is optional and only added to the payload when supplied, so
    existing responses keep their exact shape while newer endpoints (model
    registry / runtime) can attach structured, non-sensitive context such as
    the offending ``model_id``.
    """
    corr = correlation or correlation_id()
    detail: dict = {
        "code": code,
        "message": message,
        "correlation_id": corr,
    }
    if details:
        detail["details"] = details
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Correlation-ID": corr},
    )


def operation_result(payload: dict, correlation: str) -> dict:
    """Attach a correlation identifier to a successful mutation response."""
    return {**payload, "correlation_id": correlation}
