"""Render the phase-1 GUI redesign acceptance matrix offscreen.

The matrix is intentionally narrow: three representative pages across three
locales, two themes, and the standard/minimum window sizes. It uses the desktop
contract stub, so it validates UI rendering without contacting a real backend.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "client" / "pyside6"
sys.path.insert(0, str(CLIENT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from desktop_contract_stub import DesktopContractStub  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

spec = importlib.util.spec_from_file_location("audit_main", CLIENT_ROOT / "main.py")
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

LOCALES = ("zh_CN", "en_US", "ja_JP")
MODES = ("light", "dark")
SIZES = {
    "standard": (1440, 900),
    "min": (1024, 680),
}
PAGES = ("models", "chat", "settings")
STEP_TIMEOUT_MS = 15_000


class Phase1Api(DesktopContractStub):
    username = "visual-qa"

    def __init__(self):
        super().__init__()
        self._defaults.update(
            {
                "task_summary": {"total": 2, "active": 1, "needs_attention": 0, "by_status": {}},
                "get_info": {"version": "0.1.0", "edition": "3.0"},
            }
        )


def _trap_slot_exceptions(errors: list[str]) -> None:
    previous = sys.excepthook

    def hook(exc_type, exc, tb) -> None:
        errors.append(f"{exc_type.__name__}: {exc}")
        previous(exc_type, exc, tb)

    sys.excepthook = hook


def _exit(exit_code: int) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(exit_code)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "reports" / "ui-audit-redesign-phase1"),
        help="Directory for generated PNG captures.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for png in out_dir.glob("*.png"):
        png.unlink()

    app = QApplication.instance() or QApplication([])
    recovery_dir = tempfile.TemporaryDirectory()
    theme_manager = module.apply_theme(app)
    from i18n import I18n

    api = Phase1Api()
    slot_errors: list[str] = []
    _trap_slot_exceptions(slot_errors)

    translator = I18n()
    window = module.MainWindow(
        api,
        module.RecoveryManager(data_dir=os.path.join(recovery_dir.name, "state")),
        translator,
        theme_manager,
    )
    window.show()

    plan = [
        (locale, mode, size_name, page)
        for locale in LOCALES
        for mode in MODES
        for size_name in SIZES
        for page in PAGES
    ]
    failures: list[str] = []
    progress = {"at": time.monotonic(), "label": "start"}

    def watchdog() -> None:
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
        locale, mode, size_name, page = plan[index]
        progress["at"], progress["label"] = time.monotonic(), f"{locale}/{mode}/{size_name}/{page}"
        try:
            translator.set_locale(locale)
            theme_manager.set_mode(mode)
            width, height = SIZES[size_name]
            window.resize(width, height)
            window._navigate_to(page)
        except Exception as exc:
            failures.append(f"{progress['label']}: {exc!r}")
            step(index + 1)
            return

        def capture() -> None:
            try:
                path = out_dir / f"{locale}-{mode}-{size_name}-{page}.png"
                if not window.grab().save(str(path)):
                    failures.append(f"{progress['label']}: grab().save() returned False")
            except Exception as exc:
                failures.append(f"{progress['label']}: {exc!r}")
            step(index + 1)

        QTimer.singleShot(250, capture)

    def finish() -> None:
        window.close()
        recovery_dir.cleanup()
        failures.extend(f"slot: {error}" for error in slot_errors)
        captures = len(list(out_dir.glob("*.png")))
        print(f"ENDPOINTS_TOUCHED {len(api.called_endpoints())}")
        print(f"CAPTURE_COUNT {captures}")
        if captures != len(plan):
            failures.append(f"expected {len(plan)} captures, got {captures}")
        if failures:
            print("CAPTURE_FAILURES:")
            for item in failures:
                print(" -", item)
            exit_code = 1
        else:
            print("PHASE1_CAPTURES_OK")
            exit_code = 0
        app.quit()
        _exit(exit_code)

    step(0)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
