"""Phase 3: Model Manager tests."""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.database import Base
from models.records import ModelRecord
from services.model_manager import ModelManager


@pytest.fixture
def db_session():
    """In-memory SQLite with tables."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def manager(db_session):
    """ModelManager with a temp model path."""
    mgr = ModelManager(db_session)
    tmpdir = tempfile.mkdtemp()
    mgr.model_path = Path(tmpdir)
    return mgr


class TestModelManager:
    """Tests for ModelManager operations."""

    def test_list_empty(self, manager):
        models = manager.list()
        assert models == []

    def test_install(self, manager):
        model = manager.install("test-model", "huggingface", "/path/to/model", "1.5GB")
        assert model.id is not None
        assert model.name == "test-model"
        assert model.status == "available"

    def test_install_duplicate_updates(self, manager):
        manager.install("dup", "hf", "/old", "1GB")
        updated = manager.install("dup", "modelscope", "/new", "2GB")
        assert updated.path == "/new"
        assert updated.provider == "modelscope"

    def test_remove_existing(self, manager):
        model = manager.install("to-remove", "local", "/tmp/x")
        mid = model.id
        result = manager.remove(mid)
        assert result is True
        assert manager.info(mid) is None

    def test_remove_nonexistent(self, manager):
        result = manager.remove(999)
        assert result is False

    def test_info(self, manager):
        model = manager.install("info-test", "local", "/models/test")
        fetched = manager.info(model.id)
        assert fetched is not None
        assert fetched.name == "info-test"

    def test_scan_detects_gguf(self, manager):
        gguf_file = manager.model_path / "my-model.gguf"
        gguf_file.write_text("fake model data")
        discovered = manager.scan()
        names = [m.name for m in discovered]
        assert "my-model" in names

    def test_scan_detects_model_dir(self, manager):
        model_dir = manager.model_path / "bert-model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "pytorch_model.bin").write_text("fake weights")
        discovered = manager.scan()
        names = [m.name for m in discovered]
        assert "bert-model" in names

    def test_scan_empty_dir(self, manager):
        discovered = manager.scan()
        assert discovered == []

    def test_scan_nonexistent_path(self, manager):
        discovered = manager.scan("/nonexistent/path/12345")
        assert discovered == []

    def test_format_size(self, manager):
        assert manager._format_size(0) == "0.0B"
        assert manager._format_size(500) == "500.0B"
        assert manager._format_size(1024) == "1.0KB"
        assert manager._format_size(1048576) == "1.0MB"
        assert manager._format_size(1073741824) == "1.0GB"
