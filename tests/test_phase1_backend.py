"""Phase 1: FastAPI backend and config system tests."""
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app

client = TestClient(app)


def test_root_endpoint():
    """GET / should return name and version."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "ModelForge"
    assert data["version"] == "2.0"


def test_config_defaults():
    """Config should load defaults when no files present."""
    from core.config import Settings

    settings = Settings()
    assert settings.model_path == "./models"
    assert settings.database_path == "./data/modelforge.db"
    assert settings.log_level == "INFO"


def test_config_from_yaml():
    """Config should load from a yaml file without env interference."""
    from core.config import load_config

    # Clear env vars that could interfere
    for key in ("MODEL_PATH", "DATABASE_PATH", "LOG_LEVEL"):
        os.environ.pop(key, None)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write("model_path: /test/models\ndatabase_path: /test/db.sqlite\nlog_level: DEBUG\n")
        yaml_path = f.name

    try:
        settings = load_config(yaml_path)
        assert settings.model_path == "/test/models"
        assert settings.database_path == "/test/db.sqlite"
        assert settings.log_level == "DEBUG"
    finally:
        os.unlink(yaml_path)


def test_config_env_override():
    """Env vars should override yaml values."""
    from core.config import load_config

    # Clear env vars first
    for key in ("MODEL_PATH", "DATABASE_PATH", "LOG_LEVEL"):
        os.environ.pop(key, None)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write("model_path: /from/yaml\nlog_level: WARNING\n")
        yaml_path = f.name

    try:
        os.environ["MODEL_PATH"] = "/from/env"
        os.environ["LOG_LEVEL"] = "ERROR"
        settings = load_config(yaml_path)
        assert settings.model_path == "/from/env"
        assert settings.log_level == "ERROR"
    finally:
        os.unlink(yaml_path)
        os.environ.pop("MODEL_PATH", None)
        os.environ.pop("LOG_LEVEL", None)
