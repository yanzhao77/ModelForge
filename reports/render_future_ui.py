"""Render a Future Workstation snapshot for visual QA without real service actions."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
sys.path.insert(0, CLIENT_ROOT)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

spec = importlib.util.spec_from_file_location("future_main", os.path.join(CLIENT_ROOT, "main.py"))
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class FakeApi:
    username = "visual-qa"
    base_url = "http://qa.local"

    def get_info(self): return {"version": "0.1.0"}
    def list_tasks(self): return []
    def task_summary(self): return {"total": 0, "active": 0, "needs_attention": 0, "by_status": {}}
    def onboarding_state(self): return {"server_connected": True, "ready_model_count": 0, "has_sent_message": False, "has_completed_agent_run": False, "next_recommended_step": "select_model"}
    def runtime_status(self): return {"runtimes": {}}
    def list_sessions(self): return []
    def list_models(self): return []
    def list_datasets(self): return []
    def train_tasks(self): return []
    def train_templates(self): return {"lora": {}, "full": {}}
    def knowledge_documents(self): return []
    def list_agents(self): return []
    def __getattr__(self, _name): return lambda *args, **kwargs: []


def main() -> int:
    app = QApplication.instance() or QApplication([])
    module.apply_theme(app)
    recovery_dir = tempfile.TemporaryDirectory()
    theme_manager = module.apply_theme(app)
    from i18n import I18n
    window = module.MainWindow(FakeApi(), module.RecoveryManager(data_dir=os.path.join(recovery_dir.name, "state")), I18n(), theme_manager)
    window.resize(1440, 900)
    window.show()

    def capture():
        output = os.path.join(ROOT, "reports", "future-ui-offscreen.png")
        os.makedirs(os.path.dirname(output), exist_ok=True)
        window.grab().save(output)
        window.close()
        recovery_dir.cleanup()
        app.quit()

    QTimer.singleShot(1000, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
