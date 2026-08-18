"""ModelForge 2.0 - PySide6 Desktop Client (thin client over the FastAPI backend).

Login -> sessions sidebar -> streaming chat; model center / downloader / knowledge
dialogs call the REST API.
"""
import sys

from api_client.client import ModelForgeClient
from components.api_worker import AsyncApiMixin
from components.task_center import TaskCenterDock
from components.task_store import TaskStore
from pages.agent_page import AgentPage
from pages.chat_page import ChatPage
from pages.dataset_page import DatasetPage
from pages.knowledge_page import KnowledgePage
from pages.login_dialog import LoginDialog
from pages.model_dialogs import DownloadDialog, ModelCenterDialog
from pages.runtime_page import RuntimePage
from pages.session_sidebar import SessionSidebar
from pages.training_page import TrainingPage
from pages.workspace_page import WorkspacePage
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow, AsyncApiMixin):
    """主窗口：会话侧边栏 + 聊天区 + 菜单。"""

    def __init__(self, api: ModelForgeClient):
        QMainWindow.__init__(self)
        self._init_async_api()
        self.api = api
        self.setWindowTitle(f"ModelForge 3.1 - {api.username or ''}")
        self.resize(1180, 760)
        self.task_store = TaskStore(self.api, self)
        self.task_store.stream_changed.connect(self._show_task_stream_status)
        self._init_ui()
        self.task_store.start()
        self._load_status()
    def _init_ui(self):
        # 主标签页：聊天 / 数据集 / 训练 / 知识库
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # --- 标签 0: 工作台 ---
        self.workspace_page = WorkspacePage(self.task_store)
        self.workspace_page.navigate_requested.connect(self._navigate_to)
        self.tabs.addTab(self.workspace_page, "工作台")
        self.runtime_page = RuntimePage(self.api)
        self.tabs.addTab(self.runtime_page, "模型与运行时")
        # --- 标签 1: 聊天 ---
        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        self.session_sidebar = SessionSidebar(self.api)
        self.session_sidebar.session_selected.connect(self._on_session_selected)
        self.session_sidebar.session_created.connect(self._on_session_selected)
        splitter.addWidget(self.session_sidebar)

        self.chat_page = ChatPage(self.api)
        self.chat_page.session_refresher = self.session_sidebar.refresh
        splitter.addWidget(self.chat_page)
        splitter.setSizes([240, 840])
        chat_layout.addWidget(splitter)
        self.tabs.addTab(chat_tab, "聊天")

        # --- 标签 1-3: 数据集 / 训练 / 知识库 ---
        self.dataset_page = DatasetPage(self.api)
        self.tabs.addTab(self.dataset_page, "数据集")

        self.training_page = TrainingPage(self.api)
        self.tabs.addTab(self.training_page, "训练")

        self.knowledge_page = KnowledgePage(self.api)
        self.tabs.addTab(self.knowledge_page, "知识库")

        # --- 标签 4: Agent 3.0 ---
        self.agent_page = AgentPage(self.api)
        self.tabs.addTab(self.agent_page, "Agent")

        menubar = self.menuBar()
        task_menu = menubar.addMenu("任务")
        open_tasks = QAction("打开任务中心", self)
        open_tasks.setShortcut("Ctrl+J")
        open_tasks.triggered.connect(self._show_task_center)
        task_menu.addAction(open_tasks)
        self.task_center = TaskCenterDock(self.task_store, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.task_center)
        self.task_center.hide()
        model_menu = menubar.addMenu("模型")
        model_center = QAction("模型中心", self)
        model_center.triggered.connect(lambda: ModelCenterDialog(self.api, self).exec_())
        model_menu.addAction(model_center)
        download = QAction("下载 GGUF 模型", self)
        download.triggered.connect(lambda: DownloadDialog(self.api, self).exec_())
        model_menu.addAction(download)

        tools_menu = menubar.addMenu("工具")
        nav = QAction("刷新训练数据", self)
        nav.triggered.connect(self.training_page.refresh_all)
        tools_menu.addAction(nav)
        refresh = QAction("刷新会话", self)
        refresh.triggered.connect(self.session_sidebar.refresh)
        tools_menu.addAction(refresh)

        about_menu = menubar.addMenu("帮助")
        about = QAction("关于", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "关于 ModelForge",
            "<h3>ModelForge 2.1</h3><p>本地 AI Agent 工作站</p>"
            "<p>FastAPI 后端 + PySide6 瘦客户端</p>",
        ))
        about_menu.addAction(about)

        self.statusBar().showMessage(f"后端: {self.api.base_url}")

    def _load_status(self):
        self.statusBar().showMessage("正在检查后端服务…")
        self._run_api(self.api.get_info, self._show_service_status, self._show_service_error)

    def _show_service_status(self, info):
        self.statusBar().showMessage(f"后端: {self.api.base_url}  v{info.get('version')}  用户: {self.api.username}")

    def _show_service_error(self, error):
        self.statusBar().showMessage(f"后端连接失败: {error}")
    def _show_task_stream_status(self, online: bool, error: str):
        if online:
            self.statusBar().showMessage("任务实时流：已连接")
        else:
            self.statusBar().showMessage(f"任务实时流：重连中 · {error}")

    def _show_task_center(self):
        self.task_center.show()
        self.task_center.raise_()
        self.task_center.activateWindow()

    def _navigate_to(self, destination: str):
        mapping = {
            "chat": self.chat_page,
            "agents": self.agent_page,
            "knowledge": self.knowledge_page,
            "training": self.training_page,
            "models": self.runtime_page,
            "tasks": None,
        }
        target = mapping.get(destination)
        if destination == "tasks":
            self._show_task_center()
        elif target is not None:
            self.tabs.setCurrentWidget(target.parentWidget() if destination == "chat" else target)

    def _on_session_selected(self, session_id: int):
        self.chat_page.set_session(session_id)

    def closeEvent(self, event):
        self.task_store.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    api = ModelForgeClient()

    # 登录 / 注册
    login = LoginDialog(api)
    if login.exec_() != LoginDialog.Accepted:
        sys.exit(0)

    window = MainWindow(api)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
