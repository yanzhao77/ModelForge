"""Shared pytest setup for the desktop (PySide6) tests.

Two problems are handled here rather than in every GUI test file:

* Qt needs a platform plugin in headless runs, so ``offscreen`` is the default
  (tests may still override it).
* A widget graph that only the cyclic collector frees during interpreter
  shutdown is destroyed after ``QApplication`` and crashes the process with
  ``0xC0000005`` on Windows. That masked real assertion failures behind a crash
  code, so the session disposes top-level widgets while Qt is still alive.
"""

from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 - pytest hook
    """Destroy Qt objects before the interpreter tears itself down."""
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # PySide6 not installed: nothing to clean up
        return

    app = QApplication.instance()
    if app is None:
        return

    for widget in app.topLevelWidgets():
        widget.close()
        widget.setParent(None)
        widget.deleteLater()
    app.processEvents()
    gc.collect()
