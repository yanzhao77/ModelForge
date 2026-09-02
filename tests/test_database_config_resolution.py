import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

# Imported regardless of import order; env is read at call time, not import.
import tempfile  # noqa: E402

from core.database_config import (  # noqa: E402
    _DEFAULT_DB,
    diagnose_database_config,
    is_sqlite_url,
    resolve_database_url,
)


class _Settings:
    def __init__(self, database_path):
        self.database_path = database_path


def test_default_when_no_env_or_settings():
    url = resolve_database_url(_Settings(None), env={})
    assert url == f"sqlite:///{_DEFAULT_DB}"
    assert is_sqlite_url(url)


def test_settings_database_path_used_when_no_env():
    url = resolve_database_url(_Settings("/tmp/custom.db"), env={})
    assert url == "sqlite:////tmp/custom.db"


def test_database_path_env_wins_over_settings():
    url = resolve_database_url(_Settings("/tmp/from_settings.db"), env={"DATABASE_PATH": "/tmp/from_env.db"})
    assert url == "sqlite:////tmp/from_env.db"


def test_database_url_env_wins_over_everything():
    url = resolve_database_url(
        _Settings("/tmp/from_settings.db"),
        env={"DATABASE_PATH": "/tmp/from_path.db", "DATABASE_URL": "postgresql://u:p@db:5432/mf"},
    )
    assert url == "postgresql://u:p@db:5432/mf"
    assert not is_sqlite_url(url)


def test_precedence_priority_order():
    # DATABASE_URL > DATABASE_PATH > settings > default
    assert resolve_database_url(_Settings(None), env={"DATABASE_URL": "a"}) == "a"
    assert resolve_database_url(_Settings("s"), env={"DATABASE_URL": "a", "DATABASE_PATH": "b"}) == "a"
    assert resolve_database_url(_Settings("s"), env={"DATABASE_PATH": "b"}) == "sqlite:///b"
    assert resolve_database_url(_Settings("s"), env={}) == "sqlite:///s"
    assert resolve_database_url(_Settings(None), env={}) == f"sqlite:///{_DEFAULT_DB}"


def test_blank_env_values_fall_through():
    url = resolve_database_url(_Settings("/tmp/settings.db"), env={"DATABASE_URL": "  ", "DATABASE_PATH": ""})
    assert url == "sqlite:////tmp/settings.db"


def test_os_environ_default_arg():
    with tempfile.TemporaryDirectory() as td:
        os.environ["DATABASE_PATH"] = os.path.join(td, "env.db")
        try:
            url = resolve_database_url(_Settings("/tmp/settings.db"))
            assert url == f"sqlite:///{td}/env.db"
        finally:
            del os.environ["DATABASE_PATH"]


def test_diagnose_reports_origin():
    out = diagnose_database_config(_Settings("/tmp/x.db"), env={"DATABASE_URL": "postgresql://db"})
    assert "DATABASE_URL" in out
    assert "server backend" in out
    out2 = diagnose_database_config(_Settings("/tmp/x.db"), env={})
    assert "sqlite backend" in out2
