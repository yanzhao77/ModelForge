"""Desktop settings → 模型: model download source and default storage location."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.desktop

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client", "pyside6"))

from i18n.manager import I18n  # noqa: E402
from pages.settings_page import SettingsPage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeThemeManager:
    class Mode:
        value = "light"

    mode = Mode()

    def set_mode(self, _mode):
        pass


class FakeApi:
    base_url = "http://127.0.0.1:8000"
    username = "qa-user"

    def __init__(self, storage=None):
        self.saved_dirs = []
        self.saved_sources = []
        self._storage = storage or {
            "model_dir": "./models",
            "resolved_path": "/workspace/models",
            "default_path": "/workspace/models",
            "is_default": True,
            "exists": True,
            "writable": True,
            "free_bytes": 5 * 1024 * 1024 * 1024,
            "total_bytes": 20 * 1024 * 1024 * 1024,
            "entries": 4,
            "model_files": 2,
            "truncated": False,
        }

    def get_download_source(self):
        return {"source": "official", "endpoint": "https://huggingface.co"}

    def update_download_source(self, source):
        self.saved_sources.append(source)
        return {"source": source, "endpoint": "https://huggingface.co"}

    def get_model_storage(self):
        return dict(self._storage)

    def update_model_storage(self, model_dir):
        self.saved_dirs.append(model_dir)
        payload = dict(self._storage)
        payload.update(
            {
                "model_dir": model_dir,
                "resolved_path": model_dir,
                "is_default": model_dir == self._storage["default_path"],
            }
        )
        self._storage = payload
        return dict(payload)


@contextmanager
def _settings_page(api):
    """Build the page with the async boundary collapsed to a direct call.

    The patch has to stay active for the whole test: saving a directory and
    saving a download source both go through ``_run_api``.
    """

    def run_api(self, operation, on_success, _on_failure, request_key=None):
        on_success(operation())

    with patch.object(SettingsPage, "_run_api", run_api), patch(
        "pages.settings_page.QMessageBox.information"
    ):
        page = SettingsPage(api, "test", lambda: None, FakeThemeManager(), I18n())
        try:
            yield page
        finally:
            page.close()


class TestSettingsModelPage:
    def test_model_category_is_second_and_renders_the_storage_directory(self, qt_app):
        api = FakeApi()
        with _settings_page(api) as page:
            assert page.categories.item(1).text() == "模型"
            page.categories.setCurrentRow(1)
            assert page.pages.currentWidget() is page.pages.widget(1)

            assert page.model_dir_input.text() == "./models"
            status = page.model_storage_status.text()
            assert "/workspace/models" in status
            assert "已就绪" in status
            assert "5.0 GB" in status
            assert "识别到模型文件：2" in status
            assert page.model_dir_save.isEnabled()

    def test_saving_a_directory_calls_the_backend_and_reports_the_new_path(self, qt_app):
        api = FakeApi()
        with _settings_page(api) as page:
            page.model_dir_input.setText("/data/models")
            page._save_model_storage()
            assert api.saved_dirs == ["/data/models"]
            assert page.model_dir_input.text() == "/data/models"
            assert "/data/models" in page.model_storage_status.text()
            assert page.model_dir_save.isEnabled()

    def test_browse_uses_the_folder_picker(self, qt_app, tmp_path):
        api = FakeApi()
        with _settings_page(api) as page:
            with patch("pages.settings_page.QFileDialog.getExistingDirectory", return_value=str(tmp_path)) as picker:
                page.model_dir_browse.click()
            assert picker.called
            assert page.model_dir_input.text() == str(tmp_path)

    def test_restore_default_resends_the_reported_default_path(self, qt_app):
        api = FakeApi(
            storage={
                "model_dir": "/data/models",
                "resolved_path": "/data/models",
                "default_path": "/workspace/models",
                "is_default": False,
                "exists": True,
                "writable": True,
                "free_bytes": 0,
                "total_bytes": 0,
                "entries": 0,
                "model_files": 0,
                "truncated": False,
            }
        )
        with _settings_page(api) as page:
            page._reset_model_storage()
            assert api.saved_dirs == ["/workspace/models"]
            assert page.model_dir_input.text() == "/workspace/models"

    def test_blank_directory_is_rejected_before_calling_the_backend(self, qt_app):
        api = FakeApi()
        with _settings_page(api) as page:
            page.model_dir_input.setText("   ")
            page._save_model_storage()
            assert api.saved_dirs == []
            assert "请输入模型存放目录" in page.model_storage_status.text()

    def test_storage_failure_keeps_controls_usable_and_shows_the_code(self, qt_app):
        api = FakeApi()
        with _settings_page(api) as page:
            page._model_storage_failed("MODEL_DIR_NOT_WRITABLE")
            text = page.model_storage_status.text()
            assert "MODEL_DIR_NOT_WRITABLE" in text
            assert "请求未完成" in text
            assert page.model_dir_save.isEnabled()
            assert page.model_dir_browse.isEnabled()

    def test_download_source_moved_into_the_model_page_still_saves(self, qt_app):
        api = FakeApi()
        with _settings_page(api) as page:
            page.categories.setCurrentRow(1)
            page.download_source_select.setCurrentIndex(page.download_source_select.findData("hf_mirror"))
            page._save_download_source()
            assert api.saved_sources == ["hf_mirror"]
            page._download_source_failed("INVALID_RESPONSE_SHAPE:settings.download_source")
            assert "下载源设置不可用" in page.download_source_status.text()
