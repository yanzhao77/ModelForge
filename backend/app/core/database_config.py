"""Single, verifiable database URL resolution for ModelForge.

MF-SEC-003: the SQLAlchemy engine previously read only environment variables
(DATABASE_URL / DATABASE_PATH) and a hard-coded default, silently ignoring the
``database_path`` value parsed from ``config.yaml``. That could split reads and
writes across two different SQLite files or leave an operator's configured
database unused. This module centralises URL construction so every consumer
(DATABASE_URL, SQLALCHEMY_DATABASE_URL, migration preflight, startup
diagnostics) agrees on one source of truth.

Resolution priority (first match wins):
    1. ``DATABASE_URL`` environment variable (explicit deployment override)
    2. ``DATABASE_PATH`` environment variable (SQLite-only legacy override)
    3. ``settings.database_path`` (from config.yaml)
    4. the project-local default ``data/modelforge.db``
"""
import os
from pathlib import Path

_DEFAULT_DB = os.path.join(Path(__file__).resolve().parents[3], "data", "modelforge.db")


def resolve_database_url(settings, env: dict | None = None) -> str:
    """Return the resolved database URL for a given settings object.

    ``settings`` only needs a ``.database_path`` attribute. ``env`` defaults to
    ``os.environ`` so the function stays pure and unit-testable.
    """
    env = env if env is not None else os.environ
    configured_url = (env.get("DATABASE_URL") or "").strip()
    if configured_url:
        return configured_url

    db_path = (
        (env.get("DATABASE_PATH") or "").strip()
        or (getattr(settings, "database_path", None) or "").strip()
        or _DEFAULT_DB
    )
    return f"sqlite:///{db_path}"


def is_sqlite_url(url: str) -> bool:
    """Return True when ``url`` selects an embedded SQLite database."""
    return url.startswith("sqlite:")


def diagnose_database_config(settings, env: dict | None = None) -> str:
    """Produce a non-sensitive one-line summary of the resolved database URL.

    Used during startup so an operator can immediately verify the engine is
    pointing at the intended store without logging credentials or full URIs.
    """
    env = env if env is not None else os.environ
    configured_url = (env.get("DATABASE_URL") or "").strip()
    db_path = (env.get("DATABASE_PATH") or "").strip() or (
        getattr(settings, "database_path", None) or ""
    ).strip()
    if configured_url:
        origin = "DATABASE_URL"
    elif db_path:
        origin = "DATABASE_PATH or settings.database_path"
    else:
        origin = "default"
    return f"database: {origin} -> {'sqlite' if is_sqlite_url(configured_url or f'sqlite:///{db_path}') else 'server'} backend"
