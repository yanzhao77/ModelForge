"""Database engine and session configuration."""
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
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
    """Additive ALTERs for columns added after a DB was first created.

    SQLite supports ADD COLUMN; failures are ignored so fresh DBs (already
    complete) and read-only engines pass through safely.
    """
    statements = [
        "ALTER TABLE agent_runs ADD COLUMN parent_run_id VARCHAR(64)",
        "ALTER TABLE remote_provider_configs ADD COLUMN last_verified_at DATETIME",
        "ALTER TABLE remote_provider_configs ADD COLUMN verification_status VARCHAR(32) NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE remote_provider_configs ADD COLUMN verification_error_code VARCHAR(64)",
        "ALTER TABLE remote_provider_configs ADD COLUMN verified_models_json TEXT",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except OperationalError:
                # Fresh schemas already contain the additive column; legacy or read-only
                # databases are handled by the surrounding startup validation path.
                pass
