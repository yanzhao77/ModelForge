"""Regression coverage for durable, user-scoped model download tasks."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.database import SessionLocal, init_db
from models.records import DownloadTaskRecord  # noqa: F401
from services.downloader import Downloader


def test_download_task_is_persisted_user_scoped_and_path_safe():
    init_db()
    downloader = Downloader()
    with SessionLocal() as session, patch.object(downloader, "_schedule"):
        task = downloader.start("owner/demo-model", user_id=101, filename="model.gguf", db=session)
        payload = task.to_dict()
        assert payload["task_id"] == task.id
        assert "target_path" not in payload
        assert downloader.get(task.id, 101, db=session) is not None
        assert downloader.get(task.id, 202, db=session) is None
        assert [item.id for item in downloader.list(101, db=session)] == [task.id]
        assert downloader.list(202, db=session) == []
        assert session.get(DownloadTaskRecord, task.id).user_id == 101
