"""Crash marker and workspace-state recovery for the ModelForge desktop app."""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QByteArray


class RecoveryManager:
    """Stores non-sensitive UI state and preserves the latest fatal traceback."""

    def __init__(self, app_name: str = "ModelForge", data_dir: Path | None = None):
        self.data_dir = Path(data_dir or Path.home() / "Library" / "Application Support" / app_name)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "workspace-state.json"
        self.lock_path = self.data_dir / "running.json"
        self.crash_path = self.data_dir / "last-crash.json"
        self.previous_crash = self.lock_path.exists()

    def mark_started(self) -> None:
        self._write_json(self.lock_path, {"started_at": self._timestamp(), "pid": os.getpid()})

    def mark_clean_exit(self) -> None:
        self.lock_path.unlink(missing_ok=True)

    def record_exception(self, exc_type, exc_value, exc_traceback) -> None:
        self._write_json(
            self.crash_path,
            {
                "occurred_at": self._timestamp(),
                "exception_type": getattr(exc_type, "__name__", str(exc_type)),
                "message": str(exc_value),
                "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
            },
        )

    def save_window_state(self, window) -> None:
        session_id = getattr(getattr(window, "session_sidebar", None), "current_session_id", None)
        active_page = getattr(window, "active_destination", "overview")
        tabs = getattr(window, "tabs", None)
        active_tab = tabs.currentIndex() if tabs is not None else 0
        self._write_json(
            self.state_path,
            {
                "active_page": active_page,
                "active_tab": active_tab,
                "task_center_visible": window.task_center.isVisible(),
                "session_id": session_id,
                "geometry": bytes(window.saveGeometry().toBase64()).decode("ascii"),
            },
        )

    def restore_window_state(self, window) -> dict:
        state = self._read_json(self.state_path)
        if not state:
            return {}
        geometry = state.get("geometry")
        if geometry:
            window.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        destination = state.get("active_page")
        if isinstance(destination, str) and hasattr(window, "_navigate_to"):
            window._navigate_to(destination)
        else:
            tabs = getattr(window, "tabs", None)
            index = state.get("active_tab")
            if tabs is not None and isinstance(index, int) and 0 <= index < tabs.count():
                tabs.setCurrentIndex(index)
        if state.get("task_center_visible"):
            window.task_center.show()
        return state

    def install_exception_hook(self) -> None:
        original = sys.excepthook

        def handler(exc_type, exc_value, exc_traceback):
            self.record_exception(exc_type, exc_value, exc_traceback)
            original(exc_type, exc_value, exc_traceback)

        sys.excepthook = handler

    def latest_crash_summary(self) -> str:
        crash = self._read_json(self.crash_path) or {}
        return f"{crash.get('exception_type', '异常')}：{crash.get('message', '上次退出未记录具体异常。')}"

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
