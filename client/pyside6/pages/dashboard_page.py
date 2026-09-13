"""Platform dashboard: system, runtime, resources, recent activity (V2.0)."""
from __future__ import annotations

import json

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class DashboardPage(QWidget, AsyncApiMixin):
    """One screen for system status, loaded models, resources and errors."""

    REFRESH_INTERVAL_MS = 5000

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_INTERVAL_MS)
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(MFSection("平台总览", "概览"))
        header.addStretch(1)
        self.status = MFStatusBadge("正在读取平台状态", "warning")
        header.addWidget(self.status)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        layout.addLayout(header)

        grid = QGridLayout()
        self.system_label = QLabel("系统：-")
        self.system_label.setWordWrap(True)
        self.runtime_label = QLabel("运行时：-")
        self.runtime_label.setWordWrap(True)
        self.resource_label = QLabel("资源：-")
        self.resource_label.setWordWrap(True)
        self.task_label = QLabel("任务：-")
        self.task_label.setWordWrap(True)
        grid.addWidget(self.system_label, 0, 0)
        grid.addWidget(self.runtime_label, 0, 1)
        grid.addWidget(self.resource_label, 1, 0)
        grid.addWidget(self.task_label, 1, 1)
        layout.addLayout(grid)

        layout.addWidget(QLabel("最近活动与错误"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("平台活动将在此显示。")
        layout.addWidget(self.detail, 1)

    def refresh(self) -> None:
        self._run_api(self.api.dashboard, self._render, self._failed, request_key="dashboard")

    def _render(self, payload: dict) -> None:
        system = payload.get("system") or {}
        runtime = payload.get("runtime") or {}
        resources = (payload.get("resources") or {}).get("resources") or {}
        tasks = payload.get("task_summary") or {}

        self.system_label.setText(
            "系统：{status}｜模型 {ready}/{total} 就绪｜数据集 {datasets}｜知识文档 {docs}｜工作流 {workflows}".format(
                status=system.get("status", "-"),
                ready=system.get("ready_models", 0),
                total=system.get("model_root_records", 0),
                datasets=system.get("datasets", 0),
                docs=system.get("knowledge_documents", 0),
                workflows=system.get("workflows", 0),
            )
        )
        loaded = payload.get("loaded_models") or []
        self.runtime_label.setText(
            "运行时：{state}｜已加载 {count}/{cap}".format(
                state="活跃" if runtime.get("active") else "空闲",
                count=len(loaded),
                cap=runtime.get("max_instances", "-"),
            )
        )
        memory = resources.get("memory_total_bytes")
        free = resources.get("memory_available_bytes")
        self.resource_label.setText(
            "资源：{mem}｜CPU 核 {cpu}｜GPU {gpu}".format(
                mem=(
                    f"内存 {(memory - free) / 2**30:.1f}/{memory / 2**30:.1f} GB"
                    if memory and free
                    else "内存未知（未安装 psutil）"
                ),
                cpu=resources.get("cpu_count") or "-",
                gpu=resources.get("gpu_name") or "不可用",
            )
        )
        self.task_label.setText(
            f"任务：总计 {tasks.get('total', 0)}｜进行中 {tasks.get('active', 0)}｜失败 {tasks.get('failed', 0)}"
        )
        self.status.set_state("平台状态已同步", "online")

        summary = {
            "loaded_models": loaded,
            "recent_chats": payload.get("recent_chats"),
            "recent_agent_runs": payload.get("recent_agent_runs"),
            "training_tasks": payload.get("training_tasks"),
            "knowledge_bases": payload.get("knowledge_bases"),
            "workflows": payload.get("workflows"),
            "errors": payload.get("errors"),
        }
        self.detail.setPlainText(json.dumps(summary, ensure_ascii=False, indent=2))

    def _failed(self, error) -> None:
        self.status.set_state("平台状态不可用", "error")
        self.detail.setPlainText(f"无法读取平台状态：{format_api_error(error)}")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self.shutdown_async_api()
        super().closeEvent(event)
