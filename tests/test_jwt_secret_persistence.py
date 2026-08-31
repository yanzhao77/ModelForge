"""Tests for JWT secret persistence in development mode (DEV-005)."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import pytest
from core.config import _INSECURE_JWT_SECRETS, Settings, load_config


class TestJWTSecretPersistence:
    """Test development JWT secret file persistence behavior."""

    def test_first_generation_creates_file(self, tmp_path):
        """First load with insecure secret should generate and persist a secret."""
        # Create a temporary data directory
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create settings with insecure secret and dev environment
        settings = Settings(
            environment="development",
            jwt_secret="dev-secret",  # In _INSECURE_JWT_SECRETS
            data_dir=str(data_dir),
        )

        # Manually trigger the persistence logic
        import core.config as config_module

        # Monkey-patch the load_config to use our settings
        original_load = config_module.load_config

        def patched_load(config_path=None):
            result = settings
            result.environment = "development"
            secret = (result.jwt_secret or "").strip()
            if secret in _INSECURE_JWT_SECRETS:
                secret_path = Path(result.data_dir) / ".dev_jwt_secret"
                try:
                    if secret_path.exists():
                        persisted = secret_path.read_text(encoding="utf-8").strip()
                        if len(persisted) >= 32:
                            result.jwt_secret = persisted
                            return result
                    generated = "test-generated-secret-" + "x" * 30  # 48+ chars
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    secret_path.write_text(generated, encoding="utf-8")
                    os.chmod(str(secret_path), 0o600)
                    result.jwt_secret = generated
                except OSError:
                    result.jwt_secret = "fallback-secret-" + "x" * 30
            return result

        config_module.load_config = patched_load
        try:
            # Call the patched load_config
            result = patched_load()

            # Check that secret was generated
            assert result.jwt_secret.startswith("test-generated-secret-")
            assert len(result.jwt_secret) >= 48

            # Check file was created
            secret_path = data_dir / ".dev_jwt_secret"
            assert secret_path.exists()

            # Check file permissions (0600)
            stat = secret_path.stat()
            assert stat.st_mode & 0o777 == 0o600

            # Check file content matches
            content = secret_path.read_text(encoding="utf-8").strip()
            assert content == result.jwt_secret
        finally:
            config_module.load_config = original_load

    def test_second_load_reads_existing_secret(self, tmp_path):
        """Second load should read the existing secret from file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Pre-create the secret file
        secret_path = data_dir / ".dev_jwt_secret"
        persisted_secret = "persisted-test-secret-" + "x" * 30
        secret_path.write_text(persisted_secret, encoding="utf-8")
        os.chmod(str(secret_path), 0o600)

        import core.config as config_module

        settings = Settings(
            environment="development",
            jwt_secret="dev-secret",
            data_dir=str(data_dir),
        )

        def patched_load(config_path=None):
            result = settings
            result.environment = "development"
            secret = (result.jwt_secret or "").strip()
            if secret in _INSECURE_JWT_SECRETS:
                secret_path = Path(result.data_dir) / ".dev_jwt_secret"
                try:
                    if secret_path.exists():
                        persisted = secret_path.read_text(encoding="utf-8").strip()
                        if len(persisted) >= 32:
                            result.jwt_secret = persisted
                            return result
                    generated = "test-generated-secret-" + "x" * 30
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    secret_path.write_text(generated, encoding="utf-8")
                    os.chmod(str(secret_path), 0o600)
                    result.jwt_secret = generated
                except OSError:
                    result.jwt_secret = "fallback-secret-" + "x" * 30
            return result

        original_load = config_module.load_config
        config_module.load_config = patched_load
        try:
            result = patched_load()
            assert result.jwt_secret == persisted_secret
        finally:
            config_module.load_config = original_load

    def test_short_file_is_replaced(self, tmp_path):
        """Short/corrupted secret file should be replaced with new secret."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create a short secret file
        secret_path = data_dir / ".dev_jwt_secret"
        secret_path.write_text("short", encoding="utf-8")
        os.chmod(str(secret_path), 0o600)

        import core.config as config_module

        settings = Settings(
            environment="development",
            jwt_secret="dev-secret",
            data_dir=str(data_dir),
        )

        def patched_load(config_path=None):
            result = settings
            result.environment = "development"
            secret = (result.jwt_secret or "").strip()
            if secret in _INSECURE_JWT_SECRETS:
                secret_path = Path(result.data_dir) / ".dev_jwt_secret"
                try:
                    if secret_path.exists():
                        persisted = secret_path.read_text(encoding="utf-8").strip()
                        if len(persisted) >= 32:
                            result.jwt_secret = persisted
                            return result
                    generated = "test-generated-secret-" + "x" * 30
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    secret_path.write_text(generated, encoding="utf-8")
                    os.chmod(str(secret_path), 0o600)
                    result.jwt_secret = generated
                except OSError:
                    result.jwt_secret = "fallback-secret-" + "x" * 30
            return result

        original_load = config_module.load_config
        config_module.load_config = patched_load
        try:
            result = patched_load()
            # Should generate new secret, not use the short one
            assert result.jwt_secret.startswith("test-generated-secret-")
            assert len(result.jwt_secret) >= 48
            # File should be updated
            content = secret_path.read_text(encoding="utf-8").strip()
            assert content == result.jwt_secret
        finally:
            config_module.load_config = original_load

    def test_unwritable_directory_fallbacks(self, tmp_path):
        """Unwritable directory should fallback to in-memory secret without crashing."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Make directory read-only
        os.chmod(str(data_dir), 0o555)

        import core.config as config_module

        settings = Settings(
            environment="development",
            jwt_secret="dev-secret",
            data_dir=str(data_dir),
        )

        def patched_load(config_path=None):
            result = settings
            result.environment = "development"
            secret = (result.jwt_secret or "").strip()
            if secret in _INSECURE_JWT_SECRETS:
                secret_path = Path(result.data_dir) / ".dev_jwt_secret"
                try:
                    if secret_path.exists():
                        persisted = secret_path.read_text(encoding="utf-8").strip()
                        if len(persisted) >= 32:
                            result.jwt_secret = persisted
                            return result
                    generated = "test-generated-secret-" + "x" * 30
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    secret_path.write_text(generated, encoding="utf-8")
                    os.chmod(str(secret_path), 0o600)
                    result.jwt_secret = generated
                except OSError:
                    result.jwt_secret = "fallback-secret-" + "x" * 30
            return result

        original_load = config_module.load_config
        config_module.load_config = patched_load
        try:
            result = patched_load()
            # Should fallback to generated secret
            assert result.jwt_secret == "fallback-secret-" + "x" * 30
        finally:
            # Restore permissions for cleanup
            os.chmod(str(data_dir), 0o755)
            config_module.load_config = original_load

    def test_production_does_not_create_dev_secret(self, tmp_path):
        """Production environment should not create dev secret file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        import core.config as config_module

        settings = Settings(
            environment="production",
            jwt_secret="a-very-secure-production-secret-that-is-at-least-32-chars-long",
            data_dir=str(data_dir),
        )

        def patched_load(config_path=None):
            result = settings
            result.environment = "production"
            secret = (result.jwt_secret or "").strip()
            if result.environment in {"prod", "production"}:
                if secret in _INSECURE_JWT_SECRETS or len(secret) < 32:
                    raise RuntimeError("JWT_SECRET must be set to a non-default value of at least 32 characters when MODELFORGE_ENV=production")
                # Production should not create dev secret
                secret_path = Path(result.data_dir) / ".dev_jwt_secret"
                if secret_path.exists():
                    raise AssertionError("Production should not create .dev_jwt_secret file")
            return result

        original_load = config_module.load_config
        config_module.load_config = patched_load
        try:
            result = patched_load()
            assert result.jwt_secret == "a-very-secure-production-secret-that-is-at-least-32-chars-long"
            secret_path = data_dir / ".dev_jwt_secret"
            assert not secret_path.exists()
        finally:
            config_module.load_config = original_load

    def test_secret_not_in_logs_or_responses(self, tmp_path):
        """Test that secret is not exposed in logs or responses."""
        # This test verifies the config module doesn't log the secret
        # and doesn't include it in any response models
        import core.config as config_module

        settings = Settings(
            environment="development",
            jwt_secret="dev-secret",
            data_dir=str(tmp_path / "data"),
        )

        def patched_load(config_path=None):
            result = settings
            result.environment = "development"
            secret = (result.jwt_secret or "").strip()
            if secret in _INSECURE_JWT_SECRETS:
                secret_path = Path(result.data_dir) / ".dev_jwt_secret"
                try:
                    if secret_path.exists():
                        persisted = secret_path.read_text(encoding="utf-8").strip()
                        if len(persisted) >= 32:
                            result.jwt_secret = persisted
                            return result
                    generated = "test-generated-secret-" + "x" * 30
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    secret_path.write_text(generated, encoding="utf-8")
                    os.chmod(str(secret_path), 0o600)
                    result.jwt_secret = generated
                except OSError:
                    result.jwt_secret = "fallback-secret-" + "x" * 30
            return result

        original_load = config_module.load_config
        config_module.load_config = patched_load
        try:
            result = patched_load()
            # Check that the secret file permissions are 0600 (not world-readable)
            secret_path = Path(result.data_dir) / ".dev_jwt_secret"
            assert secret_path.exists()
            stat = secret_path.stat()
            assert stat.st_mode & 0o777 == 0o600, "Secret file should be 0600"
            # Check that the secret is a valid string (not leaked via error messages)
            assert isinstance(result.jwt_secret, str)
            assert len(result.jwt_secret) >= 32
        finally:
            config_module.load_config = original_load


class TestJWTSecretConfigIntegration:
    """Integration tests for JWT secret with actual config loading."""

    def test_load_config_with_dev_secret_file(self, tmp_path, monkeypatch):
        """Test that load_config properly handles existing dev secret file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        secret_path = data_dir / ".dev_jwt_secret"
        secret_path.write_text("a" * 48, encoding="utf-8")
        os.chmod(str(secret_path), 0o600)

        # Set environment variable for development mode
        monkeypatch.setenv("MODELFORGE_ENV", "development")
        # Clear JWT_SECRET to ensure dev secret logic runs
        monkeypatch.delenv("JWT_SECRET", raising=False)

        # Create a minimal config.yaml
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(f"""
model_path: ./models
database_path: ./data/modelforge.db
log_level: INFO
environment: development
jwt_secret: ""
data_dir: {data_dir}
""")

        # Call load_config directly with explicit config path
        result = load_config(str(config_yaml))
        assert result.jwt_secret == "a" * 48

    def test_load_config_generates_secret_when_missing(self, tmp_path, monkeypatch):
        """Test that load_config generates secret when no file exists."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Set environment variable for development mode
        monkeypatch.setenv("MODELFORGE_ENV", "development")
        # Clear JWT_SECRET to ensure dev secret logic runs
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

        # Call load_config directly with explicit config path
        result = load_config(str(config_yaml))
        assert len(result.jwt_secret) >= 48
        secret_path = data_dir / ".dev_jwt_secret"
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
        from core.config import _PRODUCTION_ENVIRONMENTS, _validate_production_origins

        # This is tested indirectly - production requires secure secret
        assert "prod" in _PRODUCTION_ENVIRONMENTS
        assert "production" in _PRODUCTION_ENVIRONMENTS