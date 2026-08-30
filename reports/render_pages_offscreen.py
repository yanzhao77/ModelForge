"""Render every desktop destination in both themes for visual UI audit.

Extends render_future_ui.py: walks all navigation destinations of the main
window (plus the task center dock and the login dialog) and saves one PNG per
destination/theme into reports/ui-audit/. Uses the same FakeApi stub, so no
backend service is contacted and no real action is performed.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
sys.path.insert(0, CLIENT_ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "audit_main", os.path.join(CLIENT_ROOT, "main.py")
)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class FakeApi:
    username = "visual-qa"
    base_url = "http://qa.local"

    def get_info(self):
        return {"version": "0.1.0"}

    def list_tasks(self):
        return []

    def task_summary(self):
        return {"total": 2, "active": 1, "needs_attention": 1, "by_status": {}}

    def onboarding_state(self):
        return {
            "server_connected": True,
            "ready_model_count": 0,
            "has_sent_message": False,
            "has_completed_agent_run": False,
            "next_recommended_step": "select_model",
        }

    def runtime_status(self):
        return {"runtimes": {}}

    def list_sessions(self):
        return []

    def list_models(self):
        return []

    def list_datasets(self):
        return []

    def train_tasks(self):
        return []

    def train_templates(self):
        return {"lora": {}, "full": {}}

    def knowledge_documents(self):
        return []

    def list_agents(self):
        return []

    def __getattr__(self, _name):
        return lambda *args, **kwargs: []


def main() -> int:
    app = QApplication.instance() or QApplication([])
    recovery_dir = tempfile.TemporaryDirectory()
    theme_manager = module.apply_theme(app)
    from i18n import I18n

    window = module.MainWindow(
        FakeApi(),
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

    def step(index: int) -> None:
        if index >= len(plan):
            finish()
            return
        mode, key = plan[index]
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

            dialog = LoginDialog(FakeApi())
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
        if failures:
            print("CAPTURE_FAILURES:")
            for item in failures:
                print(" -", item)
        else:
            print("ALL_CAPTURES_OK")
        app.quit()

    step(0)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
