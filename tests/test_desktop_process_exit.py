"""Process-level exit codes for the desktop entry point.

In-process tests cannot observe teardown failures: an interpreter that faults
while shutting down returns a non-zero status even though every assertion
passed. These cases therefore run ``reports/gui_exit_probe.py`` — the real
``main()`` entry path with a stubbed login dialog — in a subprocess and assert
on the exit code.

Regression origin: closing the window used to end the process with
``0xC0000409`` (a running QThread destroyed with its page) and ``0xC0000005``
(the window object graph collected after ``QApplication``). See
``docs/DESKTOP_GUI_TEST_BUG_PLAN_2026-09-13.md``.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "reports", "gui_exit_probe.py")

# mode, extra args, timeout seconds. `overrun` blocks longer than the entry
# point's 5s exit grace, so it covers the "still running at the deadline" path.
CASES = [
    ("fast", [], 90),
    ("slow", ["--block-seconds", "2.5"], 90),
    ("overrun", ["--block-seconds", "9"], 120),
    ("realclient", [], 120),
]


@pytest.mark.parametrize("mode,extra,timeout", CASES, ids=[case[0] for case in CASES])
def test_desktop_process_exits_cleanly(mode: str, extra: list[str], timeout: int) -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("MODELFORGE_DEBUG_TEARDOWN", None)

    proc = subprocess.run(
        [sys.executable, PROBE, "--mode", mode, *extra],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=ROOT,
    )
    output = f"{proc.stdout}\n{proc.stderr}"

    assert "PROBE_STARTED" in proc.stdout, output
    assert "fatal exception" not in output.lower(), output
    assert proc.returncode == 0, f"exit code {proc.returncode} for mode={mode}\n{output}"
    if mode == "overrun":
        # Proves the "worker still running at the exit deadline" branch ran
        # instead of the request quietly finishing inside the grace period.
        assert "in-flight desktop request" in output, output


def test_debug_teardown_path_also_exits_cleanly() -> None:
    """MODELFORGE_DEBUG_TEARDOWN keeps Python's shutdown; it must not crash."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MODELFORGE_DEBUG_TEARDOWN"] = "1"

    proc = subprocess.run(
        [sys.executable, PROBE, "--mode", "fast"],
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
        cwd=ROOT,
    )
    output = f"{proc.stdout}\n{proc.stderr}"

    assert "PROBE_MAIN_RETURNED 0" in proc.stdout, output
    assert "fatal exception" not in output.lower(), output
    assert proc.returncode == 0, f"exit code {proc.returncode}\n{output}"
