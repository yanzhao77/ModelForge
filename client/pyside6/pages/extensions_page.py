"""Explicit, admin-scoped governance UI for loaded runtime plugins."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget

from components.api_worker import ApiWorker


class ExtensionsPage(QWidget):
    """Shows loaded extensions without discovering, loading, or starting any of them."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self._plugins: list[dict] = []
        layout = QVBoxLayout(self)
        title = QLabel("扩展治理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel("页面只显示已加载扩展。健康检查和生命周期变更均需管理员显式点击；操作前会显示依赖、工具与影响范围。")
        note.setWordWrap(True)
        layout.addWidget(note)
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._render_detail)
        body.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.detail = QLabel("选择已加载扩展查看详情。")
        self.detail.setWordWrap(True)
        side.addWidget(self.detail, 1)
        self.health_button = QPushButton("检查健康状态")
        self.health_button.clicked.connect(self._health)
        side.addWidget(self.health_button)
        for label, action in (("启动扩展", "start"), ("停止扩展", "stop"), ("挂载扩展", "mount"), ("卸载挂载", "unmount"), ("卸载扩展", "unload")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=action: self._confirm_action(value))
            side.addWidget(button)
        self.refresh_button = QPushButton("刷新已加载扩展")
        self.refresh_button.clicked.connect(self.refresh)
        side.addWidget(self.refresh_button)
        body.addLayout(side, 2)
        layout.addLayout(body, 1)
        self.refresh()

    def _selected(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        worker = ApiWorker(self.api.list_runtime_plugins)
        worker.succeeded.connect(self._loaded)
        worker.failed.connect(lambda message: self.detail.setText("无法加载扩展：管理员权限不足或服务不可用。" if "403" in str(message) else f"无法加载扩展：{message}"))
        worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
        worker.start()
        self._worker = worker

    def _loaded(self, data: list[dict]) -> None:
        self._plugins = data or []
        self.list.clear()
        for plugin in self._plugins:
            item = QListWidgetItem(f"{plugin.get('name')} · {plugin.get('status')} · {plugin.get('version', '—')}")
            item.setData(Qt.ItemDataRole.UserRole, plugin)
            self.list.addItem(item)
        if not self._plugins:
            self.detail.setText("尚无已加载扩展。此页面不会自动发现、加载或安装扩展。")

    def _render_detail(self) -> None:
        plugin = self._selected()
        if not plugin:
            return
        self.detail.setText("\n".join([
            f"名称：{plugin.get('name')}", f"状态：{plugin.get('status')}",
            f"工具：{', '.join(plugin.get('tools') or []) or '无'}",
            f"依赖：{', '.join(plugin.get('dependencies') or []) or '无'}",
            f"错误：{plugin.get('error') or '无'}",
        ]))

    def _health(self) -> None:
        plugin = self._selected()
        if not plugin:
            return
        worker = ApiWorker(lambda: self.api.plugin_health(plugin["name"]))
        worker.succeeded.connect(lambda data: QMessageBox.information(self, "扩展健康状态", f"状态：{data.get('status')}\n扩展状态：{data.get('plugin_status')}\n错误：{data.get('error') or '无'}\n检查节流：{'本次返回缓存结果' if data.get('rate_limited') else '未节流'}\n\n健康检查不会启动、挂载或加载扩展。"))
        worker.failed.connect(lambda message: QMessageBox.warning(self, "扩展健康状态", str(message)))
        worker.start()
        self._worker = worker

    def _confirm_action(self, action: str) -> None:
        plugin = self._selected()
        if not plugin:
            return
        worker = ApiWorker(lambda: self.api.plugin_impact(plugin["name"]))
        worker.succeeded.connect(lambda impact: self._approve_action(plugin, action, impact))
        worker.failed.connect(lambda message: QMessageBox.warning(self, "扩展影响预览", str(message)))
        worker.start()
        self._worker = worker

    def _approve_action(self, plugin: dict, action: str, impact: dict) -> None:
        details = f"工具：{', '.join(impact.get('tools') or []) or '无'}\n依赖它的扩展：{', '.join(impact.get('dependents') or []) or '无'}"
        if action == "unload" and impact.get("unload_blocked"):
            QMessageBox.warning(self, "无法卸载", f"存在依赖此扩展的项目。\n{details}")
            return
        if QMessageBox.question(self, "确认扩展操作", f"将执行“{action}”于“{plugin.get('name')}”。\n\n{details}\n\n是否继续？") != QMessageBox.StandardButton.Yes:
            return
        worker = ApiWorker(lambda: self.api.plugin_lifecycle(plugin["name"], action, confirm=True))
        worker.succeeded.connect(lambda _data: self.refresh())
        worker.failed.connect(lambda message: QMessageBox.warning(self, "扩展操作失败", str(message)))
        worker.start()
        self._worker = worker
