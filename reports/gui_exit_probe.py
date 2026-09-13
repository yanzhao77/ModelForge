"""Process-level exit probe for the desktop client.

Drives the real ``client/pyside6`` entry path (``main()`` including its exit
handling) with a stubbed login dialog, so a harness can start the client,
close the window and read the *process* exit code. In-process tests cannot see
teardown crashes: an interpreter that faults while shutting down still returns
a non-zero status even when every assertion passed.

Usage::

    python reports/gui_exit_probe.py --mode fast
    python reports/gui_exit_probe.py --mode slow --block-seconds 2.5
    python reports/gui_exit_probe.py --mode overrun --block-seconds 6.5
    python reports/gui_exit_probe.py --mode realclient

Modes:

``fast``        stub API, no request in flight when the window closes.
``slow``        stub API whose first call blocks inside the exit grace window.
``overrun``     stub API whose call outlives the grace window.
``realclient``  the real ``ModelForgeClient`` against no backend (connection
                refused), which is how a user starts the client while the
                server is down.

Modal message boxes are suppressed: the probe runs headless, and a dialog would
block the event loop instead of exercising the exit path.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
if CLIENT_ROOT not in sys.path:
    sys.path.insert(0, CLIENT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from desktop_contract_stub import DesktopContractStub  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402


def _build_stub(release: threading.Event, block: bool) -> DesktopContractStub:
    """Contract-shaped stub; optionally parks one request inside the exit grace."""
    if not block:
        return DesktopContractStub()

    def blocking_list_tasks():
        release.wait(30)
        return []

    return DesktopContractStub({"list_tasks": blocking_list_tasks})


class _AutoAcceptLogin:
    """Stand-in for the login dialog: the probe asserts on the exit code."""

    Accepted = 1

    def __init__(self, api):  # noqa: ARG002 - matches LoginDialog(api)
        pass

    def exec_(self) -> int:
        return self.Accepted


def _load_desktop_main():
    spec = importlib.util.spec_from_file_location(
        "modelforge_desktop_main", os.path.join(CLIENT_ROOT, "main.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _suppress_modal_dialogs() -> None:
    for name in ("warning", "information", "critical", "question"):
        setattr(QMessageBox, name, staticmethod(lambda *args, **kwargs: QMessageBox.Ok))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("fast", "slow", "overrun", "realclient"),
        default="fast",
    )
    parser.add_argument("--close-after-ms", type=int, default=1200)
    parser.add_argument("--block-seconds", type=float, default=2.5)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _suppress_modal_dialogs()
    module = _load_desktop_main()

    release = threading.Event()
    block_seconds = 0.0 if args.mode in ("fast", "realclient") else args.block_seconds
    module.LoginDialog = _AutoAcceptLogin
    if args.mode != "realclient":
        module.ModelForgeClient = lambda: _build_stub(release, block_seconds > 0)

    shown = module.MainWindow.show

    def show_with_autoclose(self) -> None:
        shown(self)
        # Timers need a live QApplication, so they are armed from inside main().
        if block_seconds > 0:
            QTimer.singleShot(int(block_seconds * 1000), release.set)
        QTimer.singleShot(args.close_after_ms, self.close)

    module.MainWindow.show = show_with_autoclose

    sys.argv = [sys.argv[0]]
    print(f"PROBE_STARTED mode={args.mode}", flush=True)
    exit_code = module.main()
    # Reached only when teardown runs in-process (MODELFORGE_DEBUG_TEARDOWN=1);
    # the default path exits inside main() via the deterministic exit helper.
    print(f"PROBE_MAIN_RETURNED {exit_code}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
