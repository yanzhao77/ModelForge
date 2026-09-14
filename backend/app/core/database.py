"""Database engine and session configuration."""
import os
import sqlite3

from core.config import settings as _app_settings
from core.database_config import is_sqlite_url, resolve_database_url
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

# MF-SEC-003: database URL is resolved from one source of truth (DATABASE_URL >
# DATABASE_PATH > config.yaml database_path > default) so the engine never
# silently ignores the configured path.
SQLALCHEMY_DATABASE_URL = resolve_database_url(_app_settings)
DATABASE_URL = SQLALCHEMY_DATABASE_URL

IS_SQLITE = is_sqlite_url(SQLALCHEMY_DATABASE_URL)
if IS_SQLITE:
    sqlite_path = SQLALCHEMY_DATABASE_URL.removeprefix("sqlite:///")
    if sqlite_path and sqlite_path != ":memory:":
        os.makedirs(os.path.dirname(sqlite_path) or ".", exist_ok=True)

# Connection sizing is explicit for server deployments. SQLite uses the same
# pool contract but needs the driver-specific cross-thread setting.
DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "32"))
DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "16"))
DATABASE_POOL_TIMEOUT = int(os.getenv("DATABASE_POOL_TIMEOUT", "10"))
DATABASE_BUSY_TIMEOUT_MS = int(os.getenv("DATABASE_BUSY_TIMEOUT_MS", "5000"))
DATABASE_ENABLE_WAL = os.getenv("DATABASE_ENABLE_WAL", "1").strip().lower() not in {"0", "false", "no"}

_engine_options = {
    "pool_size": DATABASE_POOL_SIZE,
    "max_overflow": DATABASE_MAX_OVERFLOW,
    "pool_timeout": DATABASE_POOL_TIMEOUT,
    "pool_pre_ping": True,
}
if IS_SQLITE:
    _engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(SQLALCHEMY_DATABASE_URL, **_engine_options)


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    """Set conservative per-connection SQLite concurrency pragmas.

    WAL and a finite busy timeout reduce avoidable writer contention for the
    local, single-user deployment without turning lock failures into retries
    that might repeat side effects. Callers remain responsible for short,
    idempotent transactions and explicit error handling.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout = {max(0, DATABASE_BUSY_TIMEOUT_MS)}")
        cursor.execute("PRAGMA foreign_keys = ON")
        if DATABASE_ENABLE_WAL:
            cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
    finally:
        cursor.close()

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
    """Initialize the local SQLite schema or validate a migrated server schema."""
    if IS_SQLITE:
        Base.metadata.create_all(bind=engine)
        _apply_schema_migrations()
        return
    _verify_server_schema()


def _verify_server_schema() -> None:
    """Fail closed if a PostgreSQL deployment skipped the Alembic migration step."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception as exc:
        raise RuntimeError(
            "Server database schema is unavailable. Run `alembic upgrade head` before starting ModelForge."
        ) from exc


def _apply_schema_migrations():
    """Apply explicit, append-only SQLite migrations and persist their versions.

    Fresh databases already have every model column after ``create_all``.  For
    legacy local databases, inspect the target table first and issue an ALTER
    only for a truly missing additive column.  Unexpected database failures are
    deliberately not swallowed: treating a read-only or damaged database as
    migrated would hide a data-safety failure from the startup path.
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations")).all()}
        for version, additions, indexes in _MIGRATIONS:
            if version in applied:
                continue
            for table, column, definition in additions:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
                if rows and not any(row["name"] == column for row in rows):
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            for index_sql in indexes:
                conn.execute(text(index_sql))
            conn.execute(text("INSERT INTO schema_migrations(version) VALUES (:version)"), {"version": version})


_MIGRATIONS = (
    (
        "0001_legacy_additive_columns",
        (
            ("agent_runs", "parent_run_id", "VARCHAR(64)"),
            ("remote_provider_configs", "last_verified_at", "DATETIME"),
            ("remote_provider_configs", "verification_status", "VARCHAR(32) NOT NULL DEFAULT 'unknown'"),
            ("remote_provider_configs", "verification_error_code", "VARCHAR(64)"),
            ("remote_provider_configs", "verified_models_json", "TEXT"),
            ("scheduled_jobs", "schedule_config", "TEXT NOT NULL DEFAULT '{}'"),
            ("scheduled_jobs", "misfire_policy", "VARCHAR(24) NOT NULL DEFAULT 'skip'"),
            ("scheduled_jobs", "pending_trigger", "BOOLEAN NOT NULL DEFAULT 0"),
        ),
        (),
    ),
    (
        "0002_c3_state_and_occurrence_claims",
        (
            ("agent_runs", "state_version", "INTEGER NOT NULL DEFAULT 1"),
            ("agent_runs", "executor_lease_id", "VARCHAR(64)"),
            ("agent_runs", "lease_expires_at", "DATETIME"),
            ("agent_runs", "terminal_event_key", "VARCHAR(128)"),
            ("agent_events", "event_key", "VARCHAR(128)"),
            ("schedule_executions", "occurrence_key", "VARCHAR(160)"),
            ("schedule_executions", "claim_token", "VARCHAR(64)"),
            ("schedule_executions", "claim_expires_at", "DATETIME"),
            ("schedule_executions", "state_version", "INTEGER NOT NULL DEFAULT 1"),
            ("schedule_executions", "attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ),
        (
            "CREATE INDEX IF NOT EXISTS ix_agent_runs_status_lease ON agent_runs(status, lease_expires_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_agent_runs_terminal_event_key ON agent_runs(terminal_event_key)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_agent_events_run_key ON agent_events(run_id, event_key)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_schedule_execution_occurrence ON schedule_executions(schedule_id, occurrence_key)",
        ),
    ),
    (
        "0003_d4_task_outbox_leases",
        (
            ("task_outbox", "lease_token", "VARCHAR(64)"),
            ("task_outbox", "lease_expires_at", "DATETIME"),
            ("task_outbox", "next_attempt_at", "DATETIME"),
        ),
        (
            "CREATE INDEX IF NOT EXISTS ix_task_outbox_dispatch_lease ON task_outbox(dispatched_at, lease_expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_task_outbox_next_attempt ON task_outbox(next_attempt_at)",
        ),
    ),
    (
        # Unified model registry: capabilities + lifecycle metadata for the
        # Model Asset / Runtime Instance split. Legacy rows are backfilled by
        # ModelRegistry.backfill_capabilities() at startup.
        "0004_model_registry_capabilities",
        (
            ("models", "display_name", "VARCHAR(255)"),
            ("models", "size_bytes", "INTEGER"),
            ("models", "capabilities", "TEXT"),
            ("models", "model_metadata", "TEXT"),
            ("models", "base_model_id", "INTEGER"),
            ("models", "parent_model_id", "INTEGER"),
            ("models", "updated_time", "DATETIME"),
        ),
        (
            "CREATE INDEX IF NOT EXISTS ix_models_status ON models(status)",
            "CREATE INDEX IF NOT EXISTS ix_models_base_model_id ON models(base_model_id)",
        ),
    ),
    (
        # V1.1 Agent Runtime: agents reference models by model_id, plus the
        # runtime/multi-runtime columns V1.2 adds to the registry.
        "0005_agent_model_and_runtime_columns",
        (
            ("agents", "model_id", "INTEGER"),
            ("agents", "updated_at", "DATETIME"),
            ("models", "supported_runtimes", "TEXT"),
            ("models", "preferred_runtime", "VARCHAR(64)"),
        ),
        (
            "CREATE INDEX IF NOT EXISTS ix_agents_model_id ON agents(model_id)",
            "CREATE INDEX IF NOT EXISTS ix_models_preferred_runtime ON models(preferred_runtime)",
        ),
    ),
    (
        # Local OpenAI-compatible API: new tables are created by create_all on
        # SQLite; the migration ledger records the feature boundary and ensures
        # indexes exist for upgraded local databases.
        "0006_local_openai_api",
        (),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_local_api_keys_user_prefix ON local_api_keys(user_id, prefix)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_model_api_aliases_user_alias ON model_api_aliases(user_id, alias)",
            "CREATE INDEX IF NOT EXISTS ix_local_api_logs_user_created ON local_api_request_logs(user_id, created_at)",
        ),
    ),
    (
        "0007_local_api_runtime_settings",
        (
            ("local_api_settings", "max_concurrent_requests_per_model", "INTEGER NOT NULL DEFAULT 1"),
            ("local_api_settings", "queue_size", "INTEGER NOT NULL DEFAULT 16"),
            ("local_api_settings", "idle_unload_seconds", "INTEGER NOT NULL DEFAULT 1800"),
            ("local_api_settings", "max_upload_bytes", "INTEGER NOT NULL DEFAULT 20971520"),
            ("local_api_settings", "logging_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
            ("local_api_settings", "log_retention_days", "INTEGER NOT NULL DEFAULT 14"),
            ("local_api_settings", "temp_dir", "VARCHAR(1024)"),
        ),
        (),
    ),
    (
        "0008_multimodal_chat_foundation",
        (
            ("messages", "schema_version", "INTEGER NOT NULL DEFAULT 1"),
            ("messages", "parts_json", "TEXT"),
            ("messages", "status", "VARCHAR(32) NOT NULL DEFAULT 'completed'"),
            ("messages", "turn_id", "VARCHAR(64)"),
            ("messages", "parent_message_id", "INTEGER"),
        ),
        (
            "CREATE INDEX IF NOT EXISTS ix_messages_status ON messages(status)",
            "CREATE INDEX IF NOT EXISTS ix_messages_turn_id ON messages(turn_id)",
            "CREATE INDEX IF NOT EXISTS ix_messages_parent_message_id ON messages(parent_message_id)",
            "CREATE INDEX IF NOT EXISTS ix_attachments_user_state ON attachments(user_id, state)",
            "CREATE INDEX IF NOT EXISTS ix_attachments_user_created ON attachments(user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_attachment_derivatives_source_kind ON attachment_derivatives(source_attachment_id, kind)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_attachment ON message_attachments(message_id, attachment_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_turn_user_idempotency ON chat_turns(user_id, idempotency_key)",
            "CREATE INDEX IF NOT EXISTS ix_chat_turns_session_status ON chat_turns(session_id, status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_attempt_turn_no ON chat_attempts(turn_id, attempt_no)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_event_turn_sequence ON chat_events(turn_id, sequence)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_event_turn_key ON chat_events(turn_id, event_key)",
            "CREATE INDEX IF NOT EXISTS ix_artifacts_session_created ON artifacts(session_id, created_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_version ON artifact_versions(artifact_id, version)",
        ),
    ),
    (
        "0009_chat_message_pin_search",
        (
            ("messages", "is_pinned", "BOOLEAN NOT NULL DEFAULT 0"),
            ("messages", "pinned_at", "DATETIME"),
        ),
        (
            "CREATE INDEX IF NOT EXISTS ix_messages_is_pinned ON messages(is_pinned)",
        ),
    ),
)
