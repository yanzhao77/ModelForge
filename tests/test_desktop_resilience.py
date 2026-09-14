"""Tests for GitHub Release update selection and desktop crash recovery state."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.desktop

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from components import desktop_update
from components.desktop_update import GitHubReleaseUpdater
from components.recovery import RecoveryManager


def test_release_selection_requires_macos_installer_and_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_update.platform, "system", lambda: "Darwin")
    updater = GitHubReleaseUpdater("owner/repo", "0.1.0", update_dir=tmp_path)
    assets = [
        {"name": "ModelForge-macOS-universal2.dmg", "browser_download_url": "https://example.test/ModelForge-macOS-universal2.dmg"},
        {"name": "checksums.txt", "browser_download_url": "https://example.test/checksums.txt"},
    ]

    installer, checksum = updater._select_assets(assets)

    assert installer and installer["name"].endswith(".dmg")
    assert checksum and checksum["name"] == "checksums.txt"
    assert updater._find_checksum("a" * 64 + "  ModelForge-macOS-universal2.dmg", "ModelForge-macOS-universal2.dmg") == "a" * 64


def test_recovery_detects_unclean_exit_and_preserves_crash_summary(tmp_path):
    first = RecoveryManager(data_dir=tmp_path)
    assert first.previous_crash is False
    first.mark_started()

    restarted = RecoveryManager(data_dir=tmp_path)
    assert restarted.previous_crash is True
    try:
        raise RuntimeError("simulated desktop failure")
    except RuntimeError:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        restarted.record_exception(exc_type, exc_value, exc_traceback)

    assert "simulated desktop failure" in restarted.latest_crash_summary()
    restarted.mark_clean_exit()
    assert not restarted.lock_path.exists()


def test_recovery_does_not_show_task_center_over_restored_page(tmp_path):
    recovery = RecoveryManager(data_dir=tmp_path)
    recovery.state_path.write_text(
        json.dumps({"active_page": "videos", "task_center_visible": True}),
        encoding="utf-8",
    )

    class TaskCenter:
        shown = False

        def show(self):
            self.shown = True

    class Window:
        task_center = TaskCenter()

        def __init__(self):
            self.destinations = []

        def _navigate_to(self, destination):
            self.destinations.append(destination)

    window = Window()
    restored = recovery.restore_window_state(window)

    assert restored["active_page"] == "videos"
    assert window.destinations == ["videos"]
    assert window.task_center.shown is False
