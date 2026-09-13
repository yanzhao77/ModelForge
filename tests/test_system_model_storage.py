"""Desktop-managed model storage directory (设置 → 模型 → 默认存放地址).

The settings page lets a user point model downloads at an explicit directory.
Two invariants are asserted here because silently breaking either one leaves the
product in a state the UI cannot explain:

* the download target (``model_dir``) and the model scan root (``model_path``)
  always move together, so a freshly downloaded model stays discoverable;
* the choice is persisted, so it survives a backend restart even though the
  shipped ``.env`` sets ``MODEL_PATH=./models``.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from api.system import _resolve_model_dir  # noqa: E402
from core.config import load_config, settings  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from services.downloader import downloader  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_KEYS = ("MODEL_DIR", "MODEL_PATH", "HF_ENDPOINT")


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _register(client, username):
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": username + "@example.com"},
    )
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Restore the process-wide model location and runtime file after each test."""
    data_dir = tmp_path / "data"
    original = {key: os.environ.get(key) for key in _ENV_KEYS}
    original_dir, original_path = settings.model_dir, settings.model_path
    original_endpoint = settings.hf_endpoint
    original_data_dir = settings.data_dir
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    try:
        yield tmp_path
    finally:
        settings.model_dir, settings.model_path = original_dir, original_path
        settings.hf_endpoint = original_endpoint
        settings.data_dir = original_data_dir
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _saved_runtime_settings() -> dict:
    path = Path(settings.data_dir) / "runtime_settings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_model_storage_defaults_are_reported(client, isolated_storage):
    settings.model_dir = "./models"
    user = _register(client, "storagedefault")
    response = client.get("/api/v1/system/model-storage", headers=user)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["model_dir"] == "./models"
    assert payload["default_path"] == str(PROJECT_ROOT / "models")
    assert payload["resolved_path"] == str(PROJECT_ROOT / "models")
    assert payload["is_default"] is True
    assert isinstance(payload["free_bytes"], int)
    assert isinstance(payload["model_files"], int)


def test_model_storage_update_activates_download_and_scan_directory(client, isolated_storage):
    target = isolated_storage / "custom" / "models"
    user = _register(client, "storageupdate")
    response = client.put("/api/v1/system/model-storage", json={"model_dir": str(target)}, headers=user)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["resolved_path"] == str(target)
    assert payload["exists"] is True
    assert payload["writable"] is True
    assert payload["is_default"] is False
    assert target.is_dir()

    # Downloads must land in the new directory…
    assert downloader._target_path("org/repo") == target / "org_repo"
    # …and scanning must start from it, otherwise the download stays invisible.
    assert settings.model_dir == str(target)
    assert settings.model_path == str(target)
    assert os.environ["MODEL_DIR"] == str(target)
    assert os.environ["MODEL_PATH"] == str(target)

    saved = _saved_runtime_settings()
    assert saved["model_dir"] == str(target)
    assert saved["model_path"] == str(target)


def test_model_storage_update_survives_a_config_reload(client, isolated_storage):
    target = isolated_storage / "persisted-models"
    user = _register(client, "storagepersist")
    response = client.put("/api/v1/system/model-storage", json={"model_dir": str(target)}, headers=user)
    assert response.status_code == 200, response.text

    # A reload stands in for a restart; the explicit UI choice must win over the
    # MODEL_PATH/MODEL_DIR values the shipped .env exports.
    reloaded = load_config()
    assert reloaded.model_dir == str(target)
    assert reloaded.model_path == str(target)


def test_model_storage_update_keeps_other_runtime_settings(client, isolated_storage):
    user = _register(client, "storagemerge")
    assert client.put("/api/v1/system/download-source", json={"source": "hf_mirror"}, headers=user).status_code == 200
    target = isolated_storage / "merged-models"
    assert client.put("/api/v1/system/model-storage", json={"model_dir": str(target)}, headers=user).status_code == 200

    saved = _saved_runtime_settings()
    assert saved["hf_endpoint"] == "https://hf-mirror.com"
    assert saved["model_dir"] == str(target)


def test_model_storage_resolves_relative_paths_against_the_install_root():
    assert _resolve_model_dir("shared/models") == PROJECT_ROOT / "shared" / "models"
    assert _resolve_model_dir("  ./models  ") == PROJECT_ROOT / "models"


def test_model_storage_rejects_a_file_with_a_stable_code(client, isolated_storage):
    artifact = isolated_storage / "not-a-directory.gguf"
    artifact.write_text("weights", encoding="utf-8")
    user = _register(client, "storagefile")
    response = client.put("/api/v1/system/model-storage", json={"model_dir": str(artifact)}, headers=user)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "MODEL_DIR_NOT_A_DIRECTORY"


def test_model_storage_rejects_a_filesystem_root(client, isolated_storage):
    user = _register(client, "storageroot")
    root = Path(PROJECT_ROOT.anchor)
    assert root.parent == root  # the guard would be vacuous on a broken path
    response = client.put("/api/v1/system/model-storage", json={"model_dir": str(root)}, headers=user)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "MODEL_DIR_INVALID"


def test_model_storage_reports_model_files_and_scan_truncation(client, isolated_storage, monkeypatch):
    from api import system as system_api

    target = isolated_storage / "counted-models"
    target.mkdir(parents=True)
    (target / "model-a.gguf").write_bytes(b"a")
    (target / "model-b.safetensors").write_bytes(b"b")
    user = _register(client, "storagecount")
    assert client.put("/api/v1/system/model-storage", json={"model_dir": str(target)}, headers=user).status_code == 200

    payload = client.get("/api/v1/system/model-storage", headers=user).json()
    assert (payload["entries"], payload["model_files"], payload["truncated"]) == (2, 2, False)

    monkeypatch.setattr(system_api, "MODEL_DIR_SCAN_LIMIT", 1)
    payload = client.get("/api/v1/system/model-storage", headers=user).json()
    assert (payload["entries"], payload["model_files"], payload["truncated"]) == (1, 1, True)


def test_model_storage_rejects_blank_and_empty_values(client, isolated_storage):
    user = _register(client, "storageblank")
    blank = client.put("/api/v1/system/model-storage", json={"model_dir": "   "}, headers=user)
    assert blank.status_code == 400
    assert blank.json()["detail"]["code"] == "MODEL_DIR_INVALID"
    assert client.put("/api/v1/system/model-storage", json={"model_dir": ""}, headers=user).status_code == 422


def test_model_storage_reports_an_unwritable_directory(client, isolated_storage, monkeypatch):
    """The write probe is the contract for "I cannot store anything here"."""
    from api import system as system_api

    def _raise_read_only(**_kwargs):
        raise OSError("read-only")

    user = _register(client, "storagereadonly")
    with monkeypatch.context() as patch:
        patch.setattr(system_api.tempfile, "mkstemp", _raise_read_only)
        response = client.put(
            "/api/v1/system/model-storage",
            json={"model_dir": str(isolated_storage / "readonly-models")},
            headers=user,
        )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "MODEL_DIR_NOT_WRITABLE"
    # A rejected location must not become the active storage directory.
    assert settings.model_dir != str(isolated_storage / "readonly-models")


def test_model_storage_survives_a_corrupt_runtime_file(client, isolated_storage):
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "runtime_settings.json").write_text("{not json", encoding="utf-8")
    target = isolated_storage / "recovered-models"
    user = _register(client, "storagecorrupt")
    response = client.put("/api/v1/system/model-storage", json={"model_dir": str(target)}, headers=user)
    assert response.status_code == 200, response.text
    assert _saved_runtime_settings() == {"model_dir": str(target), "model_path": str(target)}


def test_model_storage_requires_authentication(client):
    assert client.get("/api/v1/system/model-storage").status_code == 401
    assert client.put("/api/v1/system/model-storage", json={"model_dir": "./models"}).status_code == 401
