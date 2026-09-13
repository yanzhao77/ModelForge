"""Desktop model center / chat / runtime pages over the unified registry."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.desktop

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client", "pyside6"))

from pages.chat_page import ChatPage  # noqa: E402
from pages.models_page import ModelCard, ModelsPage  # noqa: E402
from pages.runtime_page import RuntimePage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


GGUF_MODEL = {
    "id": 11,
    "model_id": 11,
    "name": "qwen-gguf",
    "display_name": None,
    "provider": "download",
    "format": "gguf",
    "quant": "Q4_K_M",
    "size": "520 MB",
    "size_bytes": 545259520,
    "status": "ready",
    "ready": True,
    "capabilities": ["CHAT", "INFERENCE"],
    "runtime_status": "loaded",
}

BASE_MODEL = {
    "id": 12,
    "model_id": 12,
    "name": "llama-base",
    "provider": "local",
    "format": "safetensors",
    "quant": None,
    "size": "2.4 GB",
    "size_bytes": 2576980377,
    "status": "ready",
    "ready": True,
    "capabilities": ["CHAT", "INFERENCE", "TRAINING", "LORA"],
    "runtime_status": "idle",
}


class FakeApi:
    base_url = "http://127.0.0.1:8000"
    username = "qa-user"

    def __init__(self):
        self.calls = []

    def list_models(self, capability=None, status=None):
        models = [dict(GGUF_MODEL), dict(BASE_MODEL)]
        if capability:
            models = [model for model in models if capability in model["capabilities"]]
        return models

    def list_remote_providers(self):
        return []

    def load_model(self, model_id, **kwargs):
        self.calls.append(("load", model_id))
        return {"model_id": model_id, "status": "loaded"}

    def unload_model(self, model_id):
        self.calls.append(("unload", model_id))
        return {"model_id": model_id, "unloaded": True}

    def set_model_default(self, model_id):
        self.calls.append(("default", model_id))
        return {"model_id": model_id}

    def model_runtime(self, model_id):
        if model_id == GGUF_MODEL["id"]:
            return {
                "active": True,
                "instance_id": "abc",
                "model_id": model_id,
                "model_name": "qwen-gguf",
                "runtime": "llama.cpp",
                "status": "loaded",
                "context_length": 4096,
                "gpu_layers": 0,
                "threads": 8,
                "memory_bytes": None,
            }
        return {"active": False, "status": "idle", "model_id": model_id}

    def runtime_status(self):
        return {"runtimes": {}}

    def list_datasets(self):
        return []

    def train_tasks(self):
        return []


def _synchronous_run_api(self, operation, on_success, on_failure, request_key=None):
    """Mirror ApiWorker: run inline but deliver failures to the page handler."""
    del self, request_key
    try:
        on_success(operation())
    except Exception as exc:  # boundary: the page's failure handler decides
        on_failure(str(exc))


def _buttons(widget):
    return {button.text(): button for button in widget.findChildren(QPushButton)}


def test_model_center_shows_capabilities_and_load_action(qt_app):
    api = FakeApi()
    with patch.object(ModelsPage, "_run_api", _synchronous_run_api), patch(
        "pages.models_page.MFStatusBadge.set_state"
    ):
        page = ModelsPage(api)
        cards = [
            page.cards_layout.itemAt(index).widget()
            for index in range(page.cards_layout.count() - 1)
        ]
        assert all(isinstance(card, ModelCard) for card in cards)
        text = "\n".join(label.text() for card in cards for label in card.findChildren(QLabel))
        assert "CHAT" in text and "TRAINING" in text
        assert "已加载" in text  # runtime status wins over the stored status

        # The loaded model offers "卸载"; the idle one offers "加载".
        loaded_buttons = _buttons(cards[0])
        idle_buttons = _buttons(cards[1])
        assert "卸载" in loaded_buttons and "加载" in idle_buttons
        idle_buttons["加载"].click()

    assert api.calls == [("load", BASE_MODEL["id"])]
    page.close()


def test_chat_page_model_selector_uses_the_registry(qt_app):
    api = FakeApi()
    with patch.object(ChatPage, "_run_api", _synchronous_run_api):
        page = ChatPage(api)
        labels = [page.local_model_select.itemText(i) for i in range(page.local_model_select.count())]
        assert labels[0] == "本地模型…"
        assert any("qwen-gguf" in label and "已加载" in label for label in labels)

        page.local_model_select.setCurrentIndex(1)
        assert page._selected_model_id == GGUF_MODEL["id"]
        assert page.model_input.text() == "qwen-gguf"
        assert page._chat_ready() is True
        assert page.send_btn.isEnabled() is True

    page.shutdown_stream()


def test_runtime_page_reports_the_active_instance(qt_app):
    api = FakeApi()
    with patch.object(RuntimePage, "_run_api", _synchronous_run_api):
        page = RuntimePage(api)
        page.model_combo.setCurrentIndex(0)
        page._render_selected(api.model_runtime(GGUF_MODEL["id"]))
        summary = page.summary.text()

    assert "qwen-gguf" in summary
    assert "llama.cpp" in summary
    assert "4096" in summary
    page.close()


def test_training_base_models_only_include_trainable_models(qt_app):
    from pages.training_page import TrainingPage

    api = FakeApi()
    with patch.object(TrainingPage, "_run_api", _synchronous_run_api):
        page = TrainingPage(api)
        labels = [page.base_model.itemText(i) for i in range(page.base_model.count())]
        data = [page.base_model.itemData(i) for i in range(page.base_model.count())]

    assert labels == ["llama-base"]
    assert data == [BASE_MODEL["id"]]
    page.close()


def test_workflow_page_lists_definitions_and_runs(qt_app):
    from pages.workflow_page import WorkflowPage

    class WorkflowApi(FakeApi):
        def list_workflows(self):
            return {
                "workflows": [
                    {
                        "workflow_id": "wf-1",
                        "name": "Sequential",
                        "definition": {"entry": "start", "nodes": [{"id": "start", "type": "input"}]},
                    }
                ],
                "node_types": ["input", "output"],
            }

        def workflow_runs(self, workflow_id, limit=50):
            return {"runs": [{"run_id": "run-1234567890", "status": "COMPLETED", "current_node": "done"}]}

        def workflow_trace(self, run_id):
            return {"trace_id": run_id, "summary": {"node_count": 3}, "spans": []}

    api = WorkflowApi()
    with patch.object(WorkflowPage, "_run_api", _synchronous_run_api):
        page = WorkflowPage(api)
        assert page.workflow_list.count() == 1
        page.workflow_list.setCurrentRow(0)
        assert "start" in page.definition.toPlainText()
        assert page.run_table.rowCount() == 1
        page.run_table.selectRow(0)
        page.show_trace()
        assert "trace_id" in page.detail.toPlainText()

    page.close()
