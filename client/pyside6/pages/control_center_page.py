"""Privacy-first control center for memory, artifacts, collections, extensions and insights."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from components.api_worker import ApiWorker


class ControlCenterPage(QWidget):
    """A read-first workspace; all persistence and export actions remain explicit."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        layout = QVBoxLayout(self)
        title = QLabel("控制中心")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("管理记忆、运行产物、知识集合、插件配置与模型洞察。页面不会启动模型、运行 Agent 或安装扩展。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tabs = QTabWidget()
        self.memory_list = QListWidget()
        self.artifact_list = QListWidget()
        self.collection_list = QListWidget()
        self.profile_list = QListWidget()
        self.insight_list = QListWidget()
        self.tabs.addTab(self._tab(self.memory_list, "新建记忆", self._create_memory), "记忆")
        self.tabs.addTab(self._tab(self.artifact_list, None, None), "产物")
        self.tabs.addTab(self._tab(self.collection_list, "新建集合", self._create_collection), "知识集合")
        self.tabs.addTab(self._tab(self.profile_list, "新建配置档", self._create_profile), "插件/MCP")
        self.tabs.addTab(self._tab(self.insight_list, None, None), "模型洞察")
        layout.addWidget(self.tabs, 1)
        self.refresh_button = QPushButton("刷新控制中心")
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.refresh()

    def _tab(self, target, action_text, callback):
        page = QWidget()
        layout = QVBoxLayout(page)
        if callback:
            button = QPushButton(action_text)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addWidget(target, 1)
        return page

    def refresh(self):
        self.refresh_button.setEnabled(False)
        worker = ApiWorker(lambda: {
            "memories": self.api.list_memories(),
            "artifacts": self.api.list_artifacts(),
            "collections": self.api.list_knowledge_collections(),
            "profiles": self.api.list_plugin_profiles(),
            "insights": self.api.model_insights().get("insights", []),
        })
        worker.succeeded.connect(self._loaded)
        worker.failed.connect(lambda error: self.insight_list.addItem(f"无法加载控制中心：{error}"))
        worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
        worker.start()
        self._worker = worker

    def _loaded(self, data):
        self._fill(self.memory_list, [f"{item.get('key')} · {item.get('type')} · 重要性 {item.get('importance')}" for item in data.get("memories", [])], "暂无记忆。")
        self._fill(self.artifact_list, [f"{item.get('title')} · {item.get('source_kind')} · 已脱敏={item.get('redacted')}" for item in data.get("artifacts", [])], "暂无运行产物。")
        self._fill(self.collection_list, [f"{item.get('name')} · {item.get('document_count', 0)} 个文档" for item in data.get("collections", [])], "暂无知识集合。")
        self._fill(self.profile_list, [item.get("name", "未命名配置档") for item in data.get("profiles", [])], "暂无插件/MCP 配置档。")
        self._fill(self.insight_list, [f"{item.get('model_ref')} · 成功 {item.get('success_count')}/{item.get('request_count')} · 平均延迟 {item.get('average_latency_ms') or '—'} ms" for item in data.get("insights", [])], "尚无脱敏聚合调用指标。")

    @staticmethod
    def _fill(target, lines, empty):
        target.clear()
        target.addItems(lines or [empty])

    def _create_memory(self):
        key, ok = QInputDialog.getText(self, "新建记忆", "键")
        if not ok or not key.strip():
            return
        value, ok = QInputDialog.getMultiLineText(self, "新建记忆", "内容")
        if ok and value.strip():
            self._call(lambda: self.api.create_memory("context", key.strip(), value.strip()))

    def _create_collection(self):
        name, ok = QInputDialog.getText(self, "新建知识集合", "名称")
        if ok and name.strip():
            self._call(lambda: self.api.create_knowledge_collection(name.strip()))

    def _create_profile(self):
        name, ok = QInputDialog.getText(self, "新建插件/MCP 配置档", "名称")
        if ok and name.strip():
            self._call(lambda: self.api.create_plugin_profile(name.strip()))

    def _call(self, action):
        worker = ApiWorker(action)
        worker.succeeded.connect(lambda _result: self.refresh())
        worker.start()
        self._worker = worker
