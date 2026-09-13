"""Read-only Agent Run Trace viewer (V1.1).

The trace is produced server-side from the durable event stream, so this dialog
only renders: run summary, span list with durations, and the raw span/event
JSON for deep inspection.
"""
from __future__ import annotations

import json

from components.api_worker import AsyncApiMixin
from i18n.ui_localizer import format_api_error
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class AgentTraceDialog(QDialog, AsyncApiMixin):
    """Show one Agent Run trace without blocking the UI thread."""

    def __init__(self, api, run_id: str, parent=None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.run_id = run_id
        self.setWindowTitle(f"Agent Trace · {run_id[:8]}")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        self.summary = QLabel("正在读取 Trace…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Trace 详情将在此显示。")
        layout.addWidget(self.detail, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_btn)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self._run_api(
            lambda: self.api.agent_run_trace(self.run_id),
            self._render,
            self._failed,
            request_key="agent.trace",
        )

    def _render(self, trace: dict) -> None:
        self.refresh_btn.setEnabled(True)
        summary = trace.get("summary") or {}
        self.summary.setText(
            "状态 {status} · 模型 {model} · 模型调用 {model_calls} · 工具调用 {tool_calls} · "
            "检索 {retrievals} · 耗时 {duration_ms} ms".format(
                status=trace.get("status", "-"),
                model=trace.get("model") or "-",
                model_calls=summary.get("model_calls", 0),
                tool_calls=summary.get("tool_calls", 0),
                retrievals=summary.get("retrievals", 0),
                duration_ms=trace.get("duration_ms", 0),
            )
        )
        lines = []
        for span in trace.get("spans") or []:
            lines.append(
                "• [{status}] {name} ({type}) · {ms} ms".format(
                    status=span.get("status", "-"),
                    name=span.get("name", "-"),
                    type=span.get("type", "-"),
                    ms=span.get("duration_ms", 0),
                )
            )
            attributes = span.get("attributes") or {}
            if attributes:
                lines.append("    " + json.dumps(attributes, ensure_ascii=False)[:400])
        if trace.get("output"):
            lines.append("")
            lines.append("最终输出：")
            lines.append(str(trace["output"]))
        if trace.get("error"):
            lines.append("")
            lines.append(f"错误：{trace['error']}")
        self.detail.setPlainText("\n".join(lines) or "该 Run 暂无 Trace 事件。")

    def _failed(self, error) -> None:
        self.refresh_btn.setEnabled(True)
        self.summary.setText("无法读取 Trace")
        self.detail.setPlainText(f"Agent Trace 不可用：{format_api_error(error)}")

    def closeEvent(self, event):
        self.shutdown_async_api()
        super().closeEvent(event)
