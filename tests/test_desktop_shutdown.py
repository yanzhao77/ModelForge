"""Closing the desktop window must not leave live background requests behind.

A page that is destroyed while one of its ApiWorker threads is still running
makes Qt abort the process (0xC0000409 on Windows), which turned "close the
window during a slow request" into a crash.
"""
import importlib.util
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
sys.path.insert(0, CLIENT_ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

_spec = importlib.util.spec_from_file_location("modelforge_desktop_main", os.path.join(CLIENT_ROOT, "main.py"))
_desktop_main = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_desktop_main)

from components.api_worker import (  # noqa: E402
    pending_api_workers,
    wait_for_api_workers,
)
from i18n import I18n  # noqa: E402

_APP = None


class FakeApi:
    username = "qa-user"
    base_url = "http://qa.local"

    def __getattr__(self, _name):
        return lambda *args, **kwargs: []


class FakeThemeManager:
    """Theme application needs a QApplication; this test only needs the API."""

    class Mode:
        value = "light"

    mode = Mode()

    def set_mode(self, _mode):
        pass


def _window(tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _desktop_main.MainWindow(
        FakeApi(),
        _desktop_main.RecoveryManager(data_dir=os.path.join(str(tmp_path), "state")),
        I18n(),
        FakeThemeManager(),
    )


def test_close_shuts_down_every_page_not_a_subset(tmp_path):
    window = _window(tmp_path)
    window.show()
    release = threading.Event()
    try:
        # The models page used to be missing from the close-event list.
        window.models_page._run_api(
            lambda: (release.wait(10), [])[1],
            lambda _result: None,
            lambda _error: None,
            request_key="models.refresh",
        )
        deadline = time.monotonic() + 2.0
        while not window.models_page._api_workers and time.monotonic() < deadline:
            _APP.processEvents()
            time.sleep(0.005)
        assert window.models_page._api_workers

        window.close()

        assert window.models_page._api_state["suppressed"] is True
        assert window.models_page._api_workers == set()
        assert window.automation_page._api_state["suppressed"] is True
        assert window.settings_page._api_state["suppressed"] is True
        assert window.developer_api_page._api_state["suppressed"] is True
    finally:
        release.set()
        assert wait_for_api_workers(5000) is True
        _APP.processEvents()  # let finished workers release themselves
        assert pending_api_workers() == 0
        window.deleteLater()
        _APP.processEvents()
