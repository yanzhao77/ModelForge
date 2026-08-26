"""Database engine and session configuration."""
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

# Resolve database path from env or default
_default_db = os.path.join(
    Path(__file__).resolve().parents[3], "data", "modelforge.db"
)
DATABASE_URL = os.getenv("DATABASE_PATH", _default_db)

# Ensure data directory exists
os.makedirs(os.path.dirname(DATABASE_URL), exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_URL}"

# SSE consumers acquire a short-lived read session on each cursor poll.
# The previous SQLAlchemy defaults (pool_size=5, max_overflow=10) rejected a
# healthy 24-connection stream cohort before outbox delivery could be measured.
# Keep the values environment-configurable so deployment sizing remains explicit.
DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "32"))
DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "16"))
DATABASE_POOL_TIMEOUT = int(os.getenv("DATABASE_POOL_TIMEOUT", "10"))

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=DATABASE_POOL_SIZE,
    max_overflow=DATABASE_MAX_OVERFLOW,
    pool_timeout=DATABASE_POOL_TIMEOUT,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables + lightweight additive migrations (no Alembic yet)."""
    Base.metadata.create_all(bind=engine)
    _additive_migrations()


def _additive_migrations():
    """Apply only explicit, safe SQLite ADD COLUMN migrations.

    Fresh databases already have every model column after ``create_all``.  For
    legacy local databases, inspect the target table first and issue an ALTER
    only for a truly missing additive column.  Unexpected database failures are
    deliberately not swallowed: treating a read-only or damaged database as
    migrated would hide a data-safety failure from the startup path.
    """
    additions = (
        ("agent_runs", "parent_run_id", "VARCHAR(64)"),
        ("remote_provider_configs", "last_verified_at", "DATETIME"),
        ("remote_provider_configs", "verification_status", "VARCHAR(32) NOT NULL DEFAULT 'unknown'"),
        ("remote_provider_configs", "verification_error_code", "VARCHAR(64)"),
        ("remote_provider_configs", "verified_models_json", "TEXT"),
        ("scheduled_jobs", "schedule_config", "TEXT NOT NULL DEFAULT '{}'"),
        ("scheduled_jobs", "misfire_policy", "VARCHAR(24) NOT NULL DEFAULT 'skip'"),
        ("scheduled_jobs", "pending_trigger", "BOOLEAN NOT NULL DEFAULT 0"),
    )
    with engine.begin() as conn:
        for table, column, definition in additions:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
            if not rows or any(row["name"] == column for row in rows):
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
