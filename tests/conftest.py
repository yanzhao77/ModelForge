"""Shared pytest setup for the desktop (PySide6) tests.

Three problems are handled here instead of in a hand-maintained file list:

* Qt needs a platform plugin in headless runs, so ``offscreen`` is the default
  (a test may still override it);
* a widget graph that only the cyclic collector frees during interpreter
  shutdown is destroyed after ``QApplication`` and crashes the process with
  ``0xC0000005`` on Windows, which masked real assertion failures behind a
  crash code — the session disposes top-level widgets while Qt is still alive;
* the set of Qt-requiring test files is discovered from their source, and those
  tests are ignored when PySide6 is missing and marked ``desktop`` otherwise, so
  CI and the documented commands cannot silently miss a newly added GUI test.
"""

from __future__ import annotations

import gc
import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The application binds its SQLAlchemy engine when `core.database` is first
# imported, so whichever module runs first decides the database for the whole
# process. Modules that set DATABASE_PATH at their own import time (e.g.
# tests/test_api_integration.py) were therefore ignored whenever an earlier
# module had already imported the app, and registration tests then collided
# with rows left in the developer's ./data database. Pin a fresh session
# database here, before any test module is imported.
_SESSION_TMP = tempfile.mkdtemp(prefix="mf_pytest_")
os.environ.setdefault("DATABASE_PATH", os.path.join(_SESSION_TMP, "test.db"))
os.environ.setdefault("JWT_SECRET", "pytest-session-secret-with-enough-length-32+")

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_QT_MARKER = "pytest.mark.desktop"


def _qt_test_files() -> list[str]:
    """Test modules that declare the ``desktop`` marker.

    The declaration lives in the test file itself, so a module that only needs
    Qt *transitively* (for example ``test_i18n_runtime.py`` importing the client
    i18n package) is covered without a hand-maintained list here or in CI.
    """
    found: list[str] = []
    for entry in sorted(os.listdir(_TESTS_DIR)):
        if not (entry.startswith("test_") and entry.endswith(".py")):
            continue
        try:
            with open(os.path.join(_TESTS_DIR, entry), encoding="utf-8") as handle:
                source = handle.read()
        except OSError:  # pragma: no cover - unreadable file
            continue
        if _QT_MARKER in source:
            found.append(entry)
    return found


QT_TEST_FILES = tuple(_qt_test_files())

try:
    # Import the module the tests actually need: an Anaconda-based interpreter
    # imports PySide6 fine but fails to load the Qt DLLs, and that layout used to
    # produce ten collection errors instead of a clean "no Qt" session.
    from PySide6.QtWidgets import QApplication  # noqa: F401

    HAS_QT = True
except Exception:  # pragma: no cover - depends on the host environment
    HAS_QT = False

# Without a Qt runtime these modules fail at import, so keep them out of the
# session entirely instead of relying on an `--ignore` list.
collect_ignore = [] if HAS_QT else list(QT_TEST_FILES)


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001 - pytest hook
    """Mark every test that needs Qt, so `-m desktop` selects them by itself."""
    for item in items:
        path = getattr(item, "path", None)
        if path is not None and path.name in QT_TEST_FILES:
            item.add_marker(pytest.mark.desktop)


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
