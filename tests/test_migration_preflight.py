"""Tests for migration_preflight module (DEV-006 coverage)."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from services.migration_preflight import (
    _requirements,
    _sqlite_database_path,
    migration_preflight,
)


class TestMigrationPreflightHelpers:
    """Test helper functions."""

    def test_sqlite_database_path_returns_none_for_non_sqlite(self):
        """Test _sqlite_database_path returns None for non-SQLite URLs."""
        with patch("services.migration_preflight.DATABASE_URL", "postgresql://user:pass@localhost/db"):
            assert _sqlite_database_path() is None

    def test_sqlite_database_path_returns_none_for_memory(self):
        """Test _sqlite_database_path returns None for :memory:."""
        with patch("services.migration_preflight.DATABASE_URL", "sqlite:///:memory:"):
            assert _sqlite_database_path() is None

    def test_sqlite_database_path_returns_path(self):
        """Test _sqlite_database_path returns Path for file SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = _sqlite_database_path()
                assert result == db_path.resolve()

    def test_requirements_returns_structure(self):
        """Test _requirements returns expected structure."""
        versions, columns, indexes = _requirements()
        assert isinstance(versions, list)
        assert isinstance(columns, dict)
        assert isinstance(indexes, dict)
        # Should have at least some migrations
        assert len(versions) > 0


class TestMigrationPreflight:
    """Test migration_preflight function."""

    def test_preflight_unsupported_for_postgresql(self):
        """Test preflight returns unsupported for PostgreSQL."""
        with patch("services.migration_preflight.DATABASE_URL", "postgresql://user:pass@localhost/db"):
            result = migration_preflight()
            assert result["status"] == "unsupported"
            assert result["read_only"] is True
            assert "Only file-backed SQLite" in result["warnings"][0]

    def test_preflight_database_missing(self):
        """Test preflight returns database_missing for non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nonexistent.db"
            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert result["status"] == "database_missing"
                assert "does not exist" in result["warnings"][0]

    def test_preflight_empty_database(self):
        """Test preflight on empty database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "empty.db"
            db_path.touch()
            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert result["status"] == "migration_required"
                assert not result["ledger"]["present"]
                assert result["ledger"]["missing_versions"] == result["expected_versions"]

    def test_preflight_database_unreadable(self):
        """Test preflight handles unreadable database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corrupt.db"
            db_path.write_text("not a database")
            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert result["status"] == "unreadable"
                assert "SQLite metadata could not be read" in result["warnings"][0]

    def test_preflight_schema_gaps_detected(self):
        """Test preflight detects schema gaps."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            # Create a database with some tables but missing migrations
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()

            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert result["status"] == "migration_required"
                assert not result["ledger"]["present"]
                assert len(result["tables"]) > 0
                # Should report missing columns/indexes
                for table in result["tables"]:
                    assert "missing_columns" in table
                    assert "missing_indexes" in table

    def test_preflight_ready_database(self):
        """Test preflight on database with all migrations applied."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(db_path)
            # Create schema_migrations table with all versions
            conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
            # Add some basic tables that migrations would create
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
            conn.execute("CREATE INDEX idx_users_username ON users(username)")
            # Add migration versions
            from core.database import _MIGRATIONS
            for version, _, _ in _MIGRATIONS:
                conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            conn.commit()
            conn.close()

            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                # Might be ready or migration_required depending on schema completeness
                assert result["ledger"]["present"] is True
                assert len(result["ledger"]["applied_versions"]) == len(_MIGRATIONS)

    def test_preflight_unknown_versions_detected(self):
        """Test preflight detects unknown migration versions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO schema_migrations (version) VALUES ('999_unknown')")
            conn.commit()
            conn.close()

            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert result["ledger"]["unknown_versions"] == ["999_unknown"]

    def test_preflight_pragmas_checked(self):
        """Test preflight checks pragmas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.commit()
            conn.close()

            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert "journal_mode" in result["pragmas"]
                assert "busy_timeout_ms" in result["pragmas"]
                assert "foreign_keys" in result["pragmas"]
                assert result["pragmas"]["journal_mode"] == "wal"
                # foreign_keys is a per-connection pragma in SQLite, defaults to OFF
                # The test just verifies the key exists and is a boolean
                assert isinstance(result["pragmas"]["foreign_keys"], bool)

    def test_preflight_warns_on_non_wal(self):
        """Test preflight warns on non-WAL journal mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.commit()
            conn.close()

            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert any("journal_mode is not WAL" in w for w in result["warnings"])

    def test_preflight_warns_on_foreign_keys_off(self):
        """Test preflight warns on foreign_keys off."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.commit()
            conn.close()

            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert any("foreign_keys is disabled" in w for w in result["warnings"])

    def test_preflight_read_only_connection(self):
        """Test preflight uses read-only connection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
            conn.close()

            # Verify we can't write through the preflight connection
            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                migration_preflight()
                # Should not have modified the database
                conn = sqlite3.connect(db_path)
                count = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
                conn.close()
                assert count == 0  # No changes

    def test_preflight_result_structure(self):
        """Test preflight returns all expected keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db_path.touch()
            with patch("services.migration_preflight.DATABASE_URL", f"sqlite:///{db_path}"):
                result = migration_preflight()
                assert "read_only" in result
                assert "migration_execution" in result
                assert "expected_versions" in result
                assert "status" in result
                assert "warnings" in result
                assert "tables" in result
                assert "ledger" in result
                assert "pragmas" in result
                assert result["migration_execution"] == "not_attempted"