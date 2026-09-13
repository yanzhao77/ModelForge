"""Render every desktop destination in both themes for visual UI audit.

Extends render_future_ui.py: walks all navigation destinations of the main
window (plus the task center dock and the login dialog) and saves one PNG per
destination/theme into reports/ui-audit/. Uses ``DesktopContractStub``, so no
backend service is contacted and no real action is performed.

The audit fails when the client raises inside a Qt slot: those exceptions are
printed by PySide6 but do not stop the run, so a "successful" capture could
otherwise hide a page that never rendered its state.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
sys.path.insert(0, CLIENT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from desktop_contract_stub import DesktopContractStub  # noqa: E402

# A step that does not advance for this long means a modal dialog or a stuck
# event loop; fail the audit instead of hanging a CI job.
STEP_TIMEOUT_MS = 15_000
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "audit_main", os.path.join(CLIENT_ROOT, "main.py")
)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class FakeApi(DesktopContractStub):
    username = "visual-qa"

    def __init__(self):
        super().__init__()
        self._defaults.update(
            {
                "task_summary": {
                    "total": 2,
                    "active": 1,
                    "needs_attention": 1,
                    "by_status": {},
                },
                "get_info": {"version": "0.1.0", "edition": "3.0"},
            }
        )


def _trap_slot_exceptions(errors: list[str]) -> None:
    """Record exceptions raised inside Qt slots instead of ignoring them."""
    previous = sys.excepthook

    def hook(exc_type, exc, tb) -> None:
        errors.append(f"{exc_type.__name__}: {exc}")
        previous(exc_type, exc, tb)

    sys.excepthook = hook


def _exit(exit_code: int) -> None:
    """Leave without Qt teardown, which crashes on Windows (0xC0000005)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(exit_code)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    recovery_dir = tempfile.TemporaryDirectory()
    theme_manager = module.apply_theme(app)
    from i18n import I18n

    api = FakeApi()
    slot_errors: list[str] = []
    _trap_slot_exceptions(slot_errors)

    window = module.MainWindow(
        api,
        module.RecoveryManager(data_dir=os.path.join(recovery_dir.name, "state")),
        I18n(),
        theme_manager,
    )
    window.resize(1440, 900)
    window.show()

    out_dir = os.path.join(ROOT, "reports", "ui-audit")
    os.makedirs(out_dir, exist_ok=True)
    destinations = list(window._pages.keys()) + ["tasks"]
    modes = ("light", "dark")
    plan = [(mode, key) for mode in modes for key in destinations]
    failures: list[str] = []
    progress = {"at": time.monotonic(), "label": "start"}

    def watchdog() -> None:
        """Fail instead of hanging when a modal dialog traps the event loop."""
        stalled_ms = (time.monotonic() - progress["at"]) * 1000
        if stalled_ms <= STEP_TIMEOUT_MS:
            return
        print(f"CAPTURE_STALLED {progress['label']} for {stalled_ms / 1000:.0f}s")
        _exit(1)

    stall_timer = QTimer()
    stall_timer.timeout.connect(watchdog)
    stall_timer.start(1000)

    def step(index: int) -> None:
        if index >= len(plan):
            finish()
            return
        mode, key = plan[index]
        progress["at"], progress["label"] = time.monotonic(), f"{mode}/{key}"
        try:
            theme_manager.set_mode(mode)
            if key == "tasks":
                window._show_task_center()
            else:
                if window.task_center.isVisible():
                    window.task_center.hide()
                window._navigate_to(key)
        except Exception as exc:  # keep auditing remaining destinations
            failures.append(f"{mode}/{key}: {exc!r}")
            step(index + 1)
            return

        def capture() -> None:
            try:
                path = os.path.join(out_dir, f"{mode}-{key}.png")
                if not window.grab().save(path):
                    failures.append(f"{mode}/{key}: grab().save() returned False")
            except Exception as exc:
                failures.append(f"{mode}/{key}: {exc!r}")
            step(index + 1)

        QTimer.singleShot(150, capture)

    def finish() -> None:
        try:
            from pages.login_dialog import LoginDialog

            dialog = LoginDialog(api)
            dialog.resize(480, 400)
            dialog.show()
            theme_manager.set_mode("dark")

            def grab_dialog() -> None:
                path = os.path.join(out_dir, "dark-login.png")
                try:
                    if not dialog.grab().save(path):
                        failures.append("login: grab().save() returned False")
                except Exception as exc:
                    failures.append(f"login: {exc!r}")
                dialog.close()
                done()
            QTimer.singleShot(150, grab_dialog)
        except Exception as exc:
            failures.append(f"login: {exc!r}")
            done()

    def done() -> None:
        window.close()
        recovery_dir.cleanup()
        failures.extend(f"slot: {error}" for error in slot_errors)
        print(f"ENDPOINTS_TOUCHED {len(api.called_endpoints())}")
        if failures:
            print("CAPTURE_FAILURES:")
            for item in failures:
                print(" -", item)
            exit_code = 1
        else:
            print("ALL_CAPTURES_OK")
            exit_code = 0
        app.quit()
        _exit(exit_code)

    step(0)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
