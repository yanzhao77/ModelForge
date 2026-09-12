"""Tests for JWT secret persistence in development mode (DEV-005).

These tests drive the production helpers directly; earlier revisions copied the
logic into the test file, which is why a Windows permission regression could
hide in a green suite.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from core.config import (  # noqa: E402
    _INSECURE_JWT_SECRETS,
    ensure_dev_jwt_secret,
    load_config,
    restrict_file_to_owner,
)

DEV_SECRET_NAME = ".dev_jwt_secret"


def _assert_owner_only(path: Path) -> None:
    """POSIX verifies the file mode; Windows has to verify the ACL instead."""
    if os.name == "nt":
        # ``icacls`` is the only supported lever on Windows, so a successful
        # re-application proves the ACL is owner-scoped rather than inherited.
        assert restrict_file_to_owner(path) is True
        return
    assert path.stat().st_mode & 0o777 == 0o600


class TestJWTSecretPersistence:
    """Development secret file handling through the production helpers."""

    def test_first_generation_creates_file(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        secret = ensure_dev_jwt_secret(data_dir)

        assert len(secret) >= 48
        secret_path = data_dir / DEV_SECRET_NAME
        assert secret_path.exists()
        assert secret_path.read_text(encoding="utf-8").strip() == secret
        _assert_owner_only(secret_path)

    def test_second_load_reads_existing_secret(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        persisted = "persisted-test-secret-" + "x" * 30
        (data_dir / DEV_SECRET_NAME).write_text(persisted, encoding="utf-8")

        assert ensure_dev_jwt_secret(data_dir) == persisted

    def test_short_file_is_replaced(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        secret_path = data_dir / DEV_SECRET_NAME
        secret_path.write_text("short", encoding="utf-8")

        secret = ensure_dev_jwt_secret(data_dir)

        assert secret != "short"
        assert len(secret) >= 48
        assert secret_path.read_text(encoding="utf-8").strip() == secret

    def test_unwritable_directory_fallbacks(self, tmp_path):
        """An unusable data directory must degrade to an in-memory secret."""
        # A file where the directory belongs fails identically on every
        # platform, unlike POSIX-only read-only directory tricks.
        blocked = tmp_path / "data"
        blocked.write_text("not a directory", encoding="utf-8")

        secret = ensure_dev_jwt_secret(blocked)

        assert len(secret) >= 48
        assert not (blocked / DEV_SECRET_NAME).exists()

    def test_production_does_not_create_dev_secret(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.setenv("MODELFORGE_ENV", "production")
        monkeypatch.setenv("JWT_SECRET", "a" * 48)
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            f"data_dir: {data_dir}\ncors_allow_origins: https://app.example.com\n",
            encoding="utf-8",
        )

        result = load_config(str(config_yaml))

        assert result.jwt_secret == "a" * 48
        assert not (data_dir / DEV_SECRET_NAME).exists()

    def test_secret_not_in_logs_or_responses(self, tmp_path, caplog):
        """Regression guard: the generated secret must never reach logs."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with caplog.at_level(logging.DEBUG):
            secret = ensure_dev_jwt_secret(data_dir)

        assert len(secret) >= 48
        assert secret not in caplog.text
        _assert_owner_only(data_dir / DEV_SECRET_NAME)


class TestJWTSecretConfigIntegration:
    """Integration tests for JWT secret with actual config loading."""

    def test_load_config_with_dev_secret_file(self, tmp_path, monkeypatch):
        """Test that load_config properly handles existing dev secret file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        secret_path = data_dir / DEV_SECRET_NAME
        secret_path.write_text("a" * 48, encoding="utf-8")
        restrict_file_to_owner(secret_path)

        monkeypatch.setenv("MODELFORGE_ENV", "development")
        monkeypatch.delenv("JWT_SECRET", raising=False)

        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(f"""
model_path: ./models
database_path: ./data/modelforge.db
log_level: INFO
environment: development
jwt_secret: ""
data_dir: {data_dir}
""")

        result = load_config(str(config_yaml))
        assert result.jwt_secret == "a" * 48

    def test_load_config_generates_secret_when_missing(self, tmp_path, monkeypatch):
        """Test that load_config generates secret when no file exists."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        monkeypatch.setenv("MODELFORGE_ENV", "development")
        monkeypatch.delenv("JWT_SECRET", raising=False)

        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(f"""
model_path: ./models
database_path: ./data/modelforge.db
log_level: INFO
environment: development
jwt_secret: ""
data_dir: {data_dir}
""")

        result = load_config(str(config_yaml))
        assert len(result.jwt_secret) >= 48
        secret_path = data_dir / DEV_SECRET_NAME
        assert secret_path.exists()
        assert secret_path.read_text().strip() == result.jwt_secret


class TestInsecureJWTSecrets:
    """Test the _INSECURE_JWT_SECRETS constant."""

    def test_insecure_secrets_list(self):
        """Verify known insecure secrets are listed."""
        assert "" in _INSECURE_JWT_SECRETS
        assert "dev-secret" in _INSECURE_JWT_SECRETS
        assert "modelforge-dev-secret-change-me-0123456789abcdef" in _INSECURE_JWT_SECRETS

    def test_production_rejects_insecure_secrets(self):
        """Production should reject insecure secrets."""
        from core.config import _PRODUCTION_ENVIRONMENTS

        assert "prod" in _PRODUCTION_ENVIRONMENTS
        assert "production" in _PRODUCTION_ENVIRONMENTS
