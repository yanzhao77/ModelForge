"""V1.4 Knowledge/RAG: parsing, knowledge bases, retrieval modes, embeddings."""

from __future__ import annotations

import io
import json
import os
import sys
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.database import Base  # noqa: E402
from main import app  # noqa: E402
from services.knowledge_base import FileParser, normalize_retrieval_mode  # noqa: E402
from services.model_registry import ModelRegistry  # noqa: E402


def _docx_bytes(paragraphs: list[str]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _auth(client: TestClient) -> dict:
    username = f"v14{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client_env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        yield {"client": client, "headers": _auth(client), "models": models, "tmp_path": tmp_path}


# ---------------- parsing ----------------


def test_csv_and_docx_are_parsed_into_text(tmp_path):
    csv_path = tmp_path / "table.csv"
    csv_path.write_text("name,role\nalice,engineer\nbob,designer\n", encoding="utf-8")
    text, metadata = FileParser().parse(str(csv_path))

    # Each row is flattened as "column: value" lines so the chunker can split it.
    assert "name: alice" in text and "role: engineer" in text
    assert metadata["type"] == "table"
    assert metadata["rows"] == 2
    assert metadata["columns"] == ["name", "role"]

    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(_docx_bytes(["项目背景", "目标是统一模型生命周期"]))
    doc_text, doc_meta = FileParser().parse(str(docx_path))

    assert "项目背景" in doc_text
    assert "统一模型生命周期" in doc_text
    assert doc_meta["type"] == "docx"


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "binary.exe"
    path.write_bytes(b"\x00\x01")

    with pytest.raises(ValueError):
        FileParser().parse(str(path))


def test_retrieval_mode_validation():
    assert normalize_retrieval_mode(None) == "semantic"
    assert normalize_retrieval_mode("HYBRID") == "hybrid"
    with pytest.raises(ValueError):
        normalize_retrieval_mode("bm25")


# ---------------- knowledge bases ----------------


def test_knowledge_base_crud_and_document_binding(client_env):
    client, headers = client_env["client"], client_env["headers"]

    created = client.post(
        "/api/v1/knowledge/bases",
        json={"name": "Project Docs", "description": "内部文档", "tags": ["docs"]},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    base = created.json()
    assert base["knowledge_id"] == base["id"]
    assert base["document_count"] == 0

    listed = client.get("/api/v1/knowledge/bases", headers=headers).json()["knowledge_bases"]
    assert [item["name"] for item in listed] == ["Project Docs"]

    detail = client.get(f"/api/v1/knowledge/bases/{base['id']}", headers=headers)
    assert detail.status_code == 200

    updated = client.patch(
        f"/api/v1/knowledge/bases/{base['id']}", json={"name": "Project Docs v2"}, headers=headers
    )
    assert updated.json()["name"] == "Project Docs v2"

    upload = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("notes.md", b"# Notes\n\nModelForge runtime plan details.", "text/markdown")},
        data={"knowledge_id": base["id"]},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["knowledge_id"] == base["id"]
    assert upload.json()["document_id"]

    documents = client.get(f"/api/v1/knowledge/bases/{base['id']}/documents", headers=headers).json()["documents"]
    assert [item["filename"] for item in documents] == ["notes.md"]

    refreshed = client.get(f"/api/v1/knowledge/bases/{base['id']}", headers=headers).json()
    assert refreshed["document_count"] == 1

    document_id = documents[0]["id"]
    detached = client.delete(
        f"/api/v1/knowledge/bases/{base['id']}/documents/{document_id}", headers=headers
    )
    assert detached.status_code == 200
    assert client.get(f"/api/v1/knowledge/bases/{base['id']}/documents", headers=headers).json()["documents"] == []
    # Detaching twice is a 404 rather than a silent success.
    assert (
        client.delete(f"/api/v1/knowledge/bases/{base['id']}/documents/{document_id}", headers=headers).status_code
        == 404
    )

    assert client.delete(f"/api/v1/knowledge/bases/{base['id']}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/knowledge/bases/{base['id']}", headers=headers).status_code == 404


def test_knowledge_bases_are_user_scoped(client_env):
    client, headers = client_env["client"], client_env["headers"]
    base = client.post("/api/v1/knowledge/bases", json={"name": "Private"}, headers=headers).json()
    other = _auth(client)

    assert client.get(f"/api/v1/knowledge/bases/{base['id']}", headers=other).status_code == 404
    assert client.get("/api/v1/knowledge/bases", headers=other).json()["knowledge_bases"] == []


# ---------------- retrieval modes ----------------


def test_retrieval_modes_change_ranking(client_env):
    client, headers = client_env["client"], client_env["headers"]
    client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("runtime.md", b"ModelForge runtime manager loads llama.cpp adapters.", "text/markdown")},
        headers=headers,
    )
    client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("training.md", b"Fine tuning uses datasets and LoRA adapters.", "text/markdown")},
        headers=headers,
    )

    for mode in ("semantic", "keyword", "hybrid", "rerank"):
        response = client.post(
            "/api/v1/knowledge/query",
            json={"question": "llama.cpp runtime adapter", "top_k": 2, "retrieval_mode": mode},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["retrieval_mode"] == mode
        assert payload["results"], mode
        assert payload["results"][0]["source"] == "runtime.md"
        assert "semantic_score" in payload["results"][0]
        assert "lexical_score" in payload["results"][0]

    invalid = client.post(
        "/api/v1/knowledge/query",
        json={"question": "x", "retrieval_mode": "bm25"},
        headers=headers,
    )
    assert invalid.status_code == 422


def test_upload_projects_an_indexing_task(client_env):
    client, headers = client_env["client"], client_env["headers"]
    client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("task.md", b"# Task\n\nindexing progress is visible", "text/markdown")},
        headers=headers,
    )

    tasks = client.get("/api/v1/tasks", headers=headers).json()["tasks"]
    indexing = [task for task in tasks if task.get("task_type") == "knowledge_index"]
    assert indexing, tasks
    assert indexing[0]["status"] in {"SUCCEEDED", "RUNNING"}
    assert indexing[0]["metadata"]["chunks"] >= 1


# ---------------- embeddings ----------------


def test_embedding_provider_defaults_to_hash_with_a_reason(client_env):
    client, headers = client_env["client"], client_env["headers"]

    status = client.get("/api/v1/knowledge/embedding", headers=headers)
    assert status.status_code == 200
    payload = status.json()
    assert payload["provider"] == "hash"
    assert payload["fallback"] is True
    assert payload["reason"] == "NO_EMBEDDING_MODEL_REGISTERED"

    embedded = client.post(
        "/api/v1/knowledge/embed", json={"texts": ["hello world", "hello world"]}, headers=headers
    )
    assert embedded.status_code == 200, embedded.text
    body = embedded.json()
    assert body["count"] == 2
    assert body["dimensions"] == 256
    assert body["vectors"][0] == body["vectors"][1]  # deterministic
    assert body["embedding"]["provider"] == "hash"

    empty = client.post("/api/v1/knowledge/embed", json={"texts": []}, headers=headers)
    assert empty.status_code == 422


def test_embedding_model_enters_the_registry_as_embedding_only(client_env, tmp_path):
    client, headers = client_env["client"], client_env["headers"]
    models = client_env["models"]
    asset = models / "bge-small"
    asset.mkdir()
    (asset / "config.json").write_text('{"model_type": "bert"}', encoding="utf-8")
    (asset / "sentence_bert_config.json").write_text("{}", encoding="utf-8")
    (asset / "model.safetensors").write_bytes(b"weights")

    installed = client.post(
        "/api/v1/models/install",
        json={"name": "bge-small", "provider": "local", "path": str(asset)},
        headers=headers,
    )
    assert installed.status_code == 200, installed.text
    model = installed.json()

    listed = client.get("/api/v1/models", params={"capability": "EMBEDDING"}, headers=headers).json()
    assert [item["name"] for item in listed] == ["bge-small"]
    chat = client.get("/api/v1/models", params={"capability": "CHAT"}, headers=headers).json()
    assert "bge-small" not in {item["name"] for item in chat}

    status = client.get(
        "/api/v1/knowledge/embedding", params={"model_id": model["id"]}, headers=headers
    ).json()
    assert model["id"] in {item["model_id"] for item in status["registered_models"]}
    if not status["transformers_available"]:
        assert status["fallback"] is True
        assert status["reason"] == "TRANSFORMERS_NOT_INSTALLED"


def test_embedding_service_is_used_by_the_knowledge_base_module():
    from services.embedding_service import HashEmbeddingProvider

    provider = HashEmbeddingProvider(dimension=32)
    vectors = provider.embed(["alpha", "alpha", "beta"])

    assert len(vectors[0]) == 32
    assert vectors[0] == vectors[1]
    assert vectors[0] != vectors[2]
