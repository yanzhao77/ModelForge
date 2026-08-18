"""Offscreen smoke verification for workspace and global task center integration."""
import importlib.util
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
sys.path.insert(0, CLIENT_ROOT)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

_spec = importlib.util.spec_from_file_location("modelforge_desktop_main", os.path.join(CLIENT_ROOT, "main.py"))
_desktop_main = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_desktop_main)
MainWindow = _desktop_main.MainWindow


class FakeApi:
    username = "qa-user"
    base_url = "http://qa.local"

    def get_info(self):
        return {"version": "3.1"}

    def list_tasks(self):
        return [{
            "task_id": "qa-task", "title": "下载示例模型", "status": "RUNNING",
            "source": "downloader", "summary": "正在下载", "progress_percent": 42,
            "cancelable": True, "updated_at": "2026-08-17T00:00:00",
        }]

    def task_summary(self):
        return {"total": 1, "active": 1, "needs_attention": 0, "by_status": {"RUNNING": 1}}

    def onboarding_state(self):
        return {"server_connected": True, "ready_model_count": 0, "has_sent_message": False,
                "has_completed_agent_run": False, "next_recommended_step": "select_model"}

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

    def cancel_task(self, task_id):
        task = self.list_tasks()[0]
        task["status"] = "CANCEL_REQUESTED"
        return task

    def __getattr__(self, _name):
        return lambda *args, **kwargs: []


def main():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(FakeApi())
    window.show()

    def verify_and_quit():
        assert window.tabs.count() == 6
        assert window.tabs.tabText(0) == "工作台"
        assert window.workspace_page.primary.text() == "准备模型"
        window._show_task_center()
        assert window.task_center.isVisible()
        window.close()
        app.quit()

    QTimer.singleShot(900, verify_and_quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
