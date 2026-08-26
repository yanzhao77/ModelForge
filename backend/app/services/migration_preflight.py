"""Read-only diagnostics for the local SQLite migration baseline.

The preflight intentionally opens the database using SQLite ``mode=ro``.  It
never invokes ``init_db()``, SQLAlchemy metadata creation, DDL, or migration
functions.  Its purpose is to make an operator-visible decision before a
future, explicitly approved startup or migration operation.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.database import DATABASE_URL, _MIGRATIONS


def _sqlite_database_path() -> Path | None:
    """Return a local SQLite database path without connecting to it."""
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix):
        return None
    raw_path = DATABASE_URL[len(prefix) :]
    if raw_path in {":memory:", ""}:
        return None
    return Path(raw_path).expanduser().resolve()


def _requirements() -> tuple[list[str], dict[str, set[str]], dict[str, set[str]]]:
    """Derive expected versions, added columns, and indexes from the ledger."""
    versions: list[str] = []
    columns: dict[str, set[str]] = defaultdict(set)
    indexes: dict[str, set[str]] = defaultdict(set)
    for version, additions, index_sql in _MIGRATIONS:
        versions.append(version)
        for table, column, _definition in additions:
            columns[table].add(column)
        for statement in index_sql:
            match = re.search(r"INDEX IF NOT EXISTS\s+([A-Za-z0-9_]+)\s+ON\s+([A-Za-z0-9_]+)", statement)
            if match:
                indexes[match.group(2)].add(match.group(1))
    return versions, columns, indexes


def migration_preflight() -> dict[str, Any]:
    """Inspect migration readiness without changing the local database.

    The result contains only schema names, migration versions, counts, and
    pragma values. It deliberately excludes the database path, table contents,
    credentials, model output, and application payloads.
    """
    expected_versions, expected_columns, expected_indexes = _requirements()
    database_path = _sqlite_database_path()
    base: dict[str, Any] = {
        "read_only": True,
        "migration_execution": "not_attempted",
        "expected_versions": expected_versions,
        "status": "blocked",
        "warnings": [],
        "tables": [],
        "ledger": {"present": False, "applied_versions": [], "missing_versions": expected_versions, "unknown_versions": []},
        "pragmas": {},
    }
    if database_path is None:
        base["status"] = "unsupported"
        base["warnings"].append("Only file-backed SQLite databases support read-only migration preflight.")
        return base
    if not database_path.exists():
        base["status"] = "database_missing"
        base["warnings"].append("The local SQLite database file does not exist; startup/migration was not attempted.")
        return base

    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        base["pragmas"] = {
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "busy_timeout_ms": connection.execute("PRAGMA busy_timeout").fetchone()[0],
            "foreign_keys": bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
        }
        ledger_present = "schema_migrations" in table_names
        applied_versions: list[str] = []
        if ledger_present:
            applied_versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        applied_set = set(applied_versions)
        expected_set = set(expected_versions)
        base["ledger"] = {
            "present": ledger_present,
            "applied_versions": applied_versions,
            "missing_versions": [item for item in expected_versions if item not in applied_set],
            "unknown_versions": sorted(applied_set - expected_set),
        }

        reports: list[dict[str, Any]] = []
        for table in sorted(set(expected_columns) | set(expected_indexes)):
            table_exists = table in table_names
            existing_columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')} if table_exists else set()
            existing_indexes = {row[1] for row in connection.execute(f'PRAGMA index_list("{table}")')} if table_exists else set()
            reports.append(
                {
                    "table": table,
                    "present": table_exists,
                    "missing_columns": sorted(expected_columns[table] - existing_columns),
                    "missing_indexes": sorted(expected_indexes[table] - existing_indexes),
                }
            )
        base["tables"] = reports
        has_schema_gap = (not ledger_present) or bool(base["ledger"]["missing_versions"]) or any(
            item["missing_columns"] or item["missing_indexes"] or not item["present"] for item in reports
        )
        if has_schema_gap:
            base["status"] = "migration_required"
            base["warnings"].append("Schema gaps were detected. This preflight did not repair or migrate the database.")
        else:
            base["status"] = "ready"
        if base["pragmas"]["journal_mode"].lower() != "wal":
            base["warnings"].append("journal_mode is not WAL on the read-only connection; configuration was not changed.")
        if not base["pragmas"]["foreign_keys"]:
            base["warnings"].append("foreign_keys is disabled on the read-only connection; configuration was not changed.")
        return base
    except sqlite3.DatabaseError as error:
        base["status"] = "unreadable"
        base["warnings"].append(f"SQLite metadata could not be read: {type(error).__name__}.")
        return base
    finally:
        connection.close()
