"""Native model-runtime control page with non-blocking lifecycle operations.

The page is a thin view over the unified runtime manager: it lists registry
models (with their live runtime status), shows the details of the single active
instance, and loads/unloads through ``/models/{id}/load|unload``. Free-text
names still fall back to the legacy per-backend runtime so an Ollama tag keeps
working.
"""
from __future__ import annotations

import json

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def _list_models(api) -> list[dict]:
    try:
        return api.list_models()
    except Exception:
        return []


class RuntimePage(QWidget, AsyncApiMixin):
    """Inventory-aware runtime launcher backed by the runtime manager."""

    #: Phase 9 keeps status synchronisation on polling; short intervals show a
    #: load/unload transition without needing an SSE channel.
    REFRESH_INTERVAL_MS = 1500

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._busy = False
        self._models: list[dict] = []
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_INTERVAL_MS)
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(MFSection("推理服务", "运行时"))
        header.addStretch(1)
        self.connection = MFStatusBadge("RUNTIME CHECKING", "warning")
        header.addWidget(self.connection)
        examples = QPushButton("示例")
        examples.clicked.connect(lambda: open_examples("runtime", self))
        header.addWidget(examples)
        layout.addLayout(header)
        subtitle = QLabel("模型生命周期、权限响应和运行时诊断均来自已连接服务。")
        subtitle.setProperty("role", "muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(320)
        self.model_combo.setToolTip("选择已登记模型，或输入其他后端模型名（例如 Ollama 标签）")
        self.model_combo.currentIndexChanged.connect(lambda _index: self._render_selected())
        controls.addWidget(self.model_combo, 1)
        self.start_btn = QPushButton("加载模型")
        self.start_btn.clicked.connect(self.start_runtime)
        controls.addWidget(self.start_btn)
        self.stop_btn = QPushButton("卸载模型")
        self.stop_btn.clicked.connect(self.stop_runtime)
        controls.addWidget(self.stop_btn)
        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)
        layout.addLayout(controls)

        self.status = QLabel("正在读取模型库存与运行时状态…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.summary = QLabel("当前没有已加载的模型。")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("运行时状态将在此显示。")
        layout.addWidget(self.output, 1)

    def _set_busy(self, busy):
        self._busy = busy
        self.start_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)

    def _selected_model(self):
        index = self.model_combo.currentIndex()
        data = self.model_combo.itemData(index) if index >= 0 else None
        return data if isinstance(data, dict) else None

    def _selected_model_id(self):
        model = self._selected_model()
        return None if not model else (model.get("model_id") or model.get("id"))

    def refresh(self):
        if self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在同步模型库存与运行时状态…")
        self._run_api(self._load_state, self._render_state, self._refresh_failed, request_key="runtime.refresh")

    def _load_state(self):
        models = _list_models(self.api)
        selected = self._selected_model_id()
        detail: dict = {}
        if selected is not None:
            try:
                detail = self.api.model_runtime(selected)
            except Exception:
                detail = {}
        else:
            try:
                detail = self.api.runtime_status()
            except Exception:
                detail = {}
        return models, detail

    def _render_state(self, result):
        self._set_busy(False)
        models, runtime = result
        self._models = [model for model in (models or []) if isinstance(model, dict)]
        previous = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in self._models:
            name = model.get("display_name") or model.get("name") or str(model.get("model_id"))
            suffix = " · 已加载" if model.get("runtime_status") == "loaded" else ""
            self.model_combo.addItem(f"{name}{suffix}", model)
        self.model_combo.setEditText(previous)
        self.model_combo.blockSignals(False)

        self.connection.set_state("运行时已同步", "online")
        self.status.setText(f"已同步 {len(self._models)} 个模型；运行时状态已刷新。")
        self._render_selected(runtime)

    def _render_selected(self, runtime=None):
        if runtime is None:
            selected = self._selected_model()
            runtime = selected or {}
            if selected is not None and selected.get("runtime_status") != "loaded":
                self.summary.setText("所选模型当前未加载。")
                self.output.setPlainText(json.dumps(selected, ensure_ascii=False, indent=2))
                return
        instance = runtime.get("instance") if isinstance(runtime, dict) else None
        detail = instance or (runtime if isinstance(runtime, dict) and runtime.get("model_id") else None)
        if isinstance(detail, dict) and detail.get("active"):
            self.summary.setText(
                "当前模型：{name}（#{model_id}）｜运行时 {runtime}｜状态 {status}\n"
                "上下文 {ctx}｜GPU Layers {gpu}｜线程 {threads}｜内存 {memory}".format(
                    name=detail.get("model_name", "-"),
                    model_id=detail.get("model_id", "-"),
                    runtime=detail.get("runtime", "-"),
                    status=detail.get("status", "-"),
                    ctx=detail.get("context_length", "-"),
                    gpu=detail.get("gpu_layers", "-"),
                    threads=detail.get("threads", "-"),
                    memory=detail.get("memory_bytes") or "-",
                )
            )
        else:
            self.summary.setText("当前没有已加载的模型。")
        self.output.setPlainText(json.dumps(runtime or {}, ensure_ascii=False, indent=2))

    def _refresh_failed(self, error):
        self._set_busy(False)
        self.status.setText(f"同步运行时状态失败：{format_api_error(error)}")
        self.connection.set_state("RUNTIME UNAVAILABLE", "error")
        self.output.setPlainText("无法读取运行时状态。请检查后端连接后重试。")

    def start_runtime(self):
        model_id = self._selected_model_id()
        if model_id is None:
            model = self.model_combo.currentText().strip()
            if not model:
                QMessageBox.information(self, "提示", "请选择或输入要启动的模型。")
                return
            self._set_busy(True)
            self.status.setText(f"正在启动运行时：{model}…")
            self._run_api(
                lambda: self.api.runtime_start(model),
                lambda result: self._operation_done("启动", model, result),
                lambda error: self._operation_failed("启动", error),
                request_key="runtime.lifecycle",
            )
            return
        self._set_busy(True)
        self.status.setText("正在通过运行时管理器加载模型…")
        self._run_api(
            lambda: self.api.load_model(model_id),
            lambda result: self._operation_done("加载", self.model_combo.currentText(), result),
            lambda error: self._operation_failed("加载", error),
            request_key="runtime.lifecycle",
        )

    def stop_runtime(self):
        model_id = self._selected_model_id()
        if model_id is None:
            model = self.model_combo.currentText().strip()
            if not model:
                QMessageBox.information(self, "提示", "请选择或输入要停止的模型。")
                return
            self._set_busy(True)
            self.status.setText(f"正在停止运行时：{model}…")
            self._run_api(
                lambda: self.api.runtime_stop(model),
                lambda result: self._operation_done("停止", model, result),
                lambda error: self._operation_failed("停止", error),
                request_key="runtime.lifecycle",
            )
            return
        self._set_busy(True)
        self.status.setText("正在卸载模型…")
        self._run_api(
            lambda: self.api.unload_model(model_id),
            lambda result: self._operation_done("卸载", self.model_combo.currentText(), result),
            lambda error: self._operation_failed("卸载", error),
            request_key="runtime.lifecycle",
        )

    def _operation_done(self, action, model, result):
        self._set_busy(False)
        self.status.setText(f"已提交{action}运行时请求：{model}。")
        self.output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        self.refresh()

    def _operation_failed(self, action, error):
        self._set_busy(False)
        self.status.setText(f"{action}运行时失败：{format_api_error(error)}")
        QMessageBox.warning(self, f"{action}运行时失败", format_api_error(error))

    def closeEvent(self, event):
        self._timer.stop()
        self.shutdown_async_api()
        super().closeEvent(event)
