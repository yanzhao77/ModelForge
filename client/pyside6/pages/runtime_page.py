"""Native model-runtime control page with non-blocking lifecycle operations."""
from __future__ import annotations

import json

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFSection, MFStatusBadge
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


class RuntimePage(QWidget, AsyncApiMixin):
    """Inventory-aware runtime launcher using the server as the authority for permissions and state."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._busy = False
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)
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
        self.model_combo.setToolTip("可输入 Ollama 模型名或选择已登记模型")
        controls.addWidget(self.model_combo, 1)
        self.start_btn = QPushButton("启动运行时")
        self.start_btn.clicked.connect(self.start_runtime)
        controls.addWidget(self.start_btn)
        self.stop_btn = QPushButton("停止运行时")
        self.stop_btn.clicked.connect(self.stop_runtime)
        controls.addWidget(self.stop_btn)
        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)
        layout.addLayout(controls)

        self.status = QLabel("正在读取模型库存与运行时状态…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
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
        return self.model_combo.currentText().strip()

    def refresh(self):
        if self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在同步模型库存与运行时状态…")
        self._run_api(lambda: (self.api.list_models(), self.api.runtime_status()), self._render_state, self._refresh_failed, request_key="runtime.refresh")

    def _render_state(self, result):
        self._set_busy(False)
        models, runtime = result
        current = self._selected_model()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in models:
            name = str(model.get("name") or model.get("id") or "")
            if name:
                self.model_combo.addItem(name)
        if current:
            self.model_combo.setCurrentText(current)
        self.model_combo.blockSignals(False)
        self.status.setText(f"已同步 {len(models)} 个模型；运行时状态已刷新。")
        self.connection.set_state("RUNTIME SYNCHRONIZED", "online")
        self.output.setPlainText(json.dumps(runtime, ensure_ascii=False, indent=2))

    def _refresh_failed(self, error):
        self._set_busy(False)
        self.status.setText(f"同步运行时状态失败：{error}")
        self.connection.set_state("RUNTIME UNAVAILABLE", "error")
        self.output.setPlainText("无法读取运行时状态。请检查后端连接后重试。")

    def start_runtime(self):
        model = self._selected_model()
        if not model:
            QMessageBox.information(self, "提示", "请选择或输入要启动的模型。")
            return
        self._set_busy(True)
        self.status.setText(f"正在启动运行时：{model}…")
        self._run_api(lambda: self.api.runtime_start(model), lambda result: self._operation_done("启动", model, result), lambda error: self._operation_failed("启动", error), request_key="runtime.lifecycle")

    def stop_runtime(self):
        model = self._selected_model()
        if not model:
            QMessageBox.information(self, "提示", "请选择或输入要停止的模型。")
            return
        self._set_busy(True)
        self.status.setText(f"正在停止运行时：{model}…")
        self._run_api(lambda: self.api.runtime_stop(model), lambda result: self._operation_done("停止", model, result), lambda error: self._operation_failed("停止", error), request_key="runtime.lifecycle")

    def _operation_done(self, action, model, result):
        self._set_busy(False)
        self.status.setText(f"已提交{action}运行时请求：{model}。")
        self.output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        self.refresh()

    def _operation_failed(self, action, error):
        self._set_busy(False)
        self.status.setText(f"{action}运行时失败：{error}")
        QMessageBox.warning(self, f"{action}运行时失败", error)

    def closeEvent(self, event):
        self._timer.stop()
        self.shutdown_async_api()
        super().closeEvent(event)
