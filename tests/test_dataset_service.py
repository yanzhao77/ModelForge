"""Unit tests for the dataset service (parser + CRUD)."""
import json
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.config import settings
from core.database import Base
from models.records import User
from services.dataset_service import DatasetParser, DatasetService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def user(db_session):
    u = User(username="dsuser", password_hash="x")
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


class TestDatasetParser:
    def test_jsonl(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write('{"q": "a", "a": "b"}\n{"q": "c", "a": "d"}\n')
            path = f.name
        try:
            count, cols, sample = DatasetParser.parse(path, "jsonl")
            assert count == 2
            assert cols == ["q", "a"]
            assert len(sample) == 2
        finally:
            os.unlink(path)

    def test_jsonl_scalar_rows(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write('"line one"\n"line two"\n')
            path = f.name
        try:
            count, cols, sample = DatasetParser.parse(path, "jsonl")
            assert count == 2
            assert cols == ["text"]
        finally:
            os.unlink(path)

    def test_csv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("question,answer\nq1,a1\nq2,a2\n")
            path = f.name
        try:
            count, cols, sample = DatasetParser.parse(path, "csv")
            assert count == 2
            assert cols == ["question", "answer"]
        finally:
            os.unlink(path)

    def test_json_list(self):
        data = [{"text": "x"}, {"text": "y"}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            path = f.name
        try:
            count, cols, sample = DatasetParser.parse(path, "json")
            assert count == 2
            assert cols == ["text"]
        finally:
            os.unlink(path)

    def test_json_train_key(self):
        data = {"train": [{"text": "x"}, {"text": "y"}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            path = f.name
        try:
            count, _, _ = DatasetParser.parse(path, "json")
            assert count == 2
        finally:
            os.unlink(path)

    def test_txt(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("hello\nworld\n")
            path = f.name
        try:
            count, cols, sample = DatasetParser.parse(path, "txt")
            assert count == 2
            assert cols == ["text"]
        finally:
            os.unlink(path)

    def test_bad_json_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write("not json at all")
            path = f.name
        try:
            with pytest.raises(Exception):
                DatasetParser.parse(path, "json")
        finally:
            os.unlink(path)

    def test_unsupported_format(self):
        with pytest.raises(ValueError):
            DatasetParser.parse("/tmp/x.bin", "bin")


class TestDatasetService:
    def test_upload_validate_delete(self, db_session, user, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "dataset_dir", str(tmp_path))
        svc = DatasetService()
        content = b'{"q": "a", "a": "b"}\n' * 3
        rec = svc.upload(db_session, user.id, "samples.jsonl", content, name="我的数据集")
        assert rec.status == "parsed"
        assert rec.row_count == 3
        assert rec.name == "我的数据集"
        assert rec.format == "jsonl"
        d = rec.to_dict()
        assert d["columns"] == ["q", "a"]
        assert len(d["sample"]) == 3

        check = svc.validate(db_session, rec.id, user.id)
        assert check["ok"] is True
        assert check["row_count"] == 3

        listed = svc.list(db_session, user.id)
        assert len(listed) == 1

        assert svc.delete(db_session, rec.id, user.id) is True
        assert svc.list(db_session, user.id) == []
        assert svc.delete(db_session, rec.id, user.id) is False

    def test_upload_rejects_bad_extension(self, db_session, user, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "dataset_dir", str(tmp_path))
        with pytest.raises(ValueError):
            DatasetService().upload(db_session, user.id, "evil.exe", b"x")

    def test_upload_marks_parse_error(self, db_session, user, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "dataset_dir", str(tmp_path))
        rec = DatasetService().upload(db_session, user.id, "bad.json", b"{invalid")
        assert rec.status == "error"
        assert rec.error