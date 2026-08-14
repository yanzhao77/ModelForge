from __future__ import annotations

import logging
from typing import Any, Optional


def get_logger(name: str = "modelforge.runtime") -> logging.Logger:
    """Return a namespaced logger (spec 81: no print())."""
    return logging.getLogger(name)


def log_run(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[int] = None,
    **fields: Any,
) -> None:
    """Structured log line; every runtime log carries run_id (spec 48)."""
    parts = [message]
    if run_id:
        parts.append(f"run_id={run_id}")
    if agent_id:
        parts.append(f"agent_id={agent_id}")
    if session_id is not None:
        parts.append(f"session_id={session_id}")
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    logger.log(level, " | ".join(parts))