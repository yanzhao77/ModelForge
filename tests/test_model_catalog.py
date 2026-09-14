import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app
from services.downloader import get_downloader
from services.model_catalog import CatalogQuery, ModelCatalogService, parse_hf_repo_id


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth_with_user(client, prefix):
    username = f"{prefix}-{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": f"{username}@example.com"})
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["token"]}, login.json()["user"]["id"]


class FakeAdapter:
    source_id = "huggingface"

    def search(self, query):
        return [
            {
                "repo_id": "owner/text-gguf",
                "task_category": "text-generation",
                "formats": ["GGUF"],
                "library": "transformers",
                "gated": False,
                "compatibility": {"runnable": True},
            },
            {
                "repo_id": "owner/clip-vision",
                "task_category": "vision",
                "formats": ["SafeTensors", "Transformers"],
                "library": "transformers",
                "gated": True,
                "compatibility": {"runnable": False},
            },
        ]

    def detail(self, repo_id):
        return {"repo_id": repo_id}


def test_parse_hugging_face_model_url():
    assert parse_hf_repo_id("https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/tree/main") == "Qwen/Qwen2.5-0.5B-Instruct"
    assert parse_hf_repo_id("BAAI/bge-small-en-v1.5") == "BAAI/bge-small-en-v1.5"


def test_catalog_service_keeps_source_contract_filterable():
    service = ModelCatalogService(adapters=[FakeAdapter()])
    results = service.search(CatalogQuery(category="vision", gated=True, compatible=False))
    assert [item["repo_id"] for item in results] == ["owner/clip-vision"]


def test_hf_detail_recommends_single_gguf_quantization(monkeypatch, tmp_path):
    from services import model_catalog

    class FakeHfApi:
        def __init__(self, endpoint=None):
            pass

        def model_info(self, repo_id, files_metadata=False):
            return SimpleNamespace(
                modelId=repo_id,
                author="owner",
                tags=["gguf", "text-generation"],
                pipeline_tag="text-generation",
                library_name="transformers",
                downloads=10,
                likes=1,
                sha="abc",
                siblings=[
                    SimpleNamespace(rfilename="model-Q4_K_M.gguf", size=100, lfs=SimpleNamespace(sha256="")),
                    SimpleNamespace(rfilename="model-Q8_0.gguf", size=300, lfs=SimpleNamespace(sha256="")),
                    SimpleNamespace(rfilename="model-F16.gguf", size=900, lfs=SimpleNamespace(sha256="")),
                    SimpleNamespace(rfilename="README.md", size=10, lfs=None),
                ],
            )

    monkeypatch.setattr(model_catalog, "_readme_excerpt", lambda repo_id, endpoint: "readme")
    monkeypatch.setattr(model_catalog, "_disk_free_bytes", lambda path: 10_000)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeHfApi))

    detail = model_catalog.HuggingFaceCatalogAdapter(endpoint="").detail("owner/text-gguf")

    assert detail["task_category"] == "text-generation"
    assert "GGUF" in detail["formats"]
    assert detail["recommended_files"] == ["model-Q4_K_M.gguf", "model-Q8_0.gguf"]


def test_hf_detail_recommends_weight_plus_support_files(monkeypatch):
    from services import model_catalog

    class FakeHfApi:
        def __init__(self, endpoint=None):
            pass

        def model_info(self, repo_id, files_metadata=False):
            return SimpleNamespace(
                modelId=repo_id,
                author="BAAI",
                tags=["sentence-transformers", "safetensors"],
                pipeline_tag="feature-extraction",
                library_name="sentence-transformers",
                downloads=5,
                likes=2,
                sha="abc",
                siblings=[
                    SimpleNamespace(rfilename="config.json", size=100, lfs=None),
                    SimpleNamespace(rfilename="tokenizer.json", size=100, lfs=None),
                    SimpleNamespace(rfilename="model.safetensors", size=1024, lfs=SimpleNamespace(sha256="")),
                    SimpleNamespace(rfilename="pytorch_model.bin", size=2048, lfs=SimpleNamespace(sha256="")),
                ],
            )

    monkeypatch.setattr(model_catalog, "_readme_excerpt", lambda repo_id, endpoint: "")
    monkeypatch.setattr(model_catalog, "_disk_free_bytes", lambda path: 10_000)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeHfApi))

    detail = model_catalog.HuggingFaceCatalogAdapter(endpoint="").detail("BAAI/bge")

    assert detail["task_category"] == "embedding"
    assert detail["recommended_files"] == ["config.json", "tokenizer.json", "model.safetensors"]


def test_download_api_persists_file_selection_and_dedupes(client, monkeypatch):
    headers, _user_id = auth_with_user(client, "catalogdl")
    downloader = get_downloader()
    monkeypatch.setattr(downloader, "_schedule", lambda task_id: None)

    payload = {
        "repo_id": "https://huggingface.co/owner/text-gguf",
        "files": ["model-Q4_K_M.gguf"],
        "include_support_files": True,
        "full_repository": False,
    }
    first = client.post("/api/v1/models/download", json=payload, headers=headers)
    second = client.post("/api/v1/models/download", json=payload, headers=headers)
    listed = client.get("/api/v1/models/download", headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["task_id"] == second.json()["task_id"]
    assert first.json()["repo_id"] == "owner/text-gguf"
    assert first.json()["plan"]["files"] == ["model-Q4_K_M.gguf"]
    assert listed.status_code == 200, listed.text
    assert any(item["task_id"] == first.json()["task_id"] for item in listed.json()["tasks"])


def test_download_api_cancel_marks_task_cancelled(client, monkeypatch):
    headers, _user_id = auth_with_user(client, "catalogcancel")
    downloader = get_downloader()
    monkeypatch.setattr(downloader, "_schedule", lambda task_id: None)
    created = client.post(
        "/api/v1/models/download",
        json={"repo_id": "owner/cancel-model", "files": ["model.safetensors"]},
        headers=headers,
    )
    assert created.status_code == 200, created.text

    cancelled = client.post(f"/api/v1/models/download/{created.json()['task_id']}/cancel", json={}, headers=headers)

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
