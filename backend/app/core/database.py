"""Database engine and session configuration."""
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Resolve database path from env or default
_default_db = os.path.join(
    Path(__file__).resolve().parents[3], "data", "modelforge.db"
)
DATABASE_URL = os.getenv("DATABASE_PATH", _default_db)

# Ensure data directory exists
os.makedirs(os.path.dirname(DATABASE_URL), exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_URL}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
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
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass
