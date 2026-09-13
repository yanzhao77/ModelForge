"""ModelForge Future AI Workstation desktop entry point."""

from __future__ import annotations

import gc
import logging
import os
import sys
from pathlib import Path

from api_client.client import ModelForgeClient
from components.api_worker import (
    AsyncApiMixin,
    log_pending_api_workers,
    wait_for_api_workers,
)
from components.app_shell import AppShell
from components.command_palette import CommandPalette
from components.desktop_update import GitHubReleaseUpdater, UpdateInfo
from components.model_readiness_store import ModelReadinessStore
from components.onboarding import OnboardingCoordinator
from components.recovery import RecoveryManager
from components.task_center import TaskCenterDock
from components.task_store import TaskStore
from i18n import I18n
from i18n.ui_localizer import format_api_error, localize_tree
from pages.activity_page import ActivityPage
from pages.agent_page import AgentPage
from pages.agent_workbench_page import AgentWorkbenchPage
from pages.automation_page import AutomationPage
from pages.chat_page import ChatPage
from pages.control_center_page import ControlCenterPage
from pages.dataset_page import DatasetPage
from pages.developer_api_page import DeveloperApiPage
from pages.extensions_page import ExtensionsPage
from pages.knowledge_page import KnowledgePage
from pages.login_dialog import LoginDialog
from pages.model_dialogs import DownloadDialog, ModelCenterDialog
from pages.models_page import ModelsPage
from pages.runtime_page import RuntimePage
from pages.session_sidebar import SessionSidebar
from pages.settings_page import SettingsPage
from pages.training_page import TrainingPage
from pages.workspace_page import WorkspacePage
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from theme.metrics import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
from theme.theme import apply_theme
from version import APP_NAME, APP_VERSION, UPDATE_REPOSITORY


class MainWindow(QMainWindow, AsyncApiMixin):
    PAGE_TITLES = {
        "overview": "概览",
        "chat": "对话",
        "models": "模型",
        "datasets": "数据集",
        "training": "训练",
        "knowledge": "知识库",
        "agents": "智能体",
        "workbench": "Agent 工作台",
        "extensions": "扩展治理",
        "developer": "开发者 API",
        "tasks": "任务",
        "runtime": "运行时",
        "activity": "活动",
        "settings": "设置",
    }

    def __init__(
        self,
        api: ModelForgeClient,
        recovery: RecoveryManager,
        translator: I18n,
        theme_manager,
    ):
        QMainWindow.__init__(self)
        self._init_async_api()
        self.api, self.recovery = api, recovery
        self.translator, self.theme_manager = translator, theme_manager
        self.translator.changed.connect(self._retranslate)
        self.updater = GitHubReleaseUpdater(UPDATE_REPOSITORY, APP_VERSION)
        self.active_destination = "overview"
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} · 本地 AI 工作区")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(1440, 900)
        self.task_store = TaskStore(self.api, self)
        self.readiness_store = ModelReadinessStore(self.api, self)
        self.onboarding = OnboardingCoordinator(
            self.api,
            self.readiness_store,
            self.recovery,
            self.api.username or "desktop-user",
            self.translator,
            self,
        )
        self.task_store.stream_changed.connect(self._show_task_stream_status)
        self.task_store.changed.connect(self._show_download_footer)
        self._init_ui()
        restored = self.recovery.restore_window_state(self)
        self.task_store.start()
        self._load_status()
        QTimer.singleShot(0, lambda: self._offer_recovery(restored))
        QTimer.singleShot(450, lambda: self.readiness_store.refresh(force=True))
        # Owned by the window so closing it cancels the check: a bare
        # `QTimer.singleShot` fired after the window was gone and reached
        # GitHub from a process that was already shutting down.
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setSingleShot(True)
        self._update_check_timer.timeout.connect(lambda: self._check_for_updates(False))
        self._update_check_timer.start(_UPDATE_CHECK_DELAY_MS)

    def _init_ui(self) -> None:
        self.shell = AppShell(self.translator)
        self.shell.destination_requested.connect(self._navigate_to)
        self.shell.footer_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.shell.footer_bar.customContextMenuRequested.connect(self._open_download_footer_menu)
        self.shell.footer.setContextMenuPolicy(Qt.CustomContextMenu)
        self.shell.footer.customContextMenuRequested.connect(self._open_download_footer_menu)
        self.shell.footer_progress.setContextMenuPolicy(Qt.CustomContextMenu)
        self.shell.footer_progress.customContextMenuRequested.connect(self._open_download_footer_menu)
        self.setCentralWidget(self.shell)
        self.stack = QStackedWidget()
        self.shell.content_layout.addWidget(self.stack, 1)
        self.workspace_page = WorkspacePage(self.task_store, self.readiness_store)
        self.workspace_page.navigate_requested.connect(self._navigate_to)
        self.models_page = ModelsPage(self.api, self.readiness_store)
        self.models_page.navigate_requested.connect(self._navigate_to)
        self.runtime_page = RuntimePage(self.api)
        self.session_sidebar = SessionSidebar(self.api)
        self.session_sidebar.session_selected.connect(self._on_session_selected)
        self.session_sidebar.session_created.connect(self._on_session_selected)
        self.chat_page = ChatPage(self.api, self.readiness_store)
        self.chat_page.session_refresher = self.session_sidebar.refresh
        chat_surface = QWidget()
        chat_layout = QVBoxLayout(chat_surface)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_splitter = QSplitter(Qt.Horizontal)
        chat_splitter.addWidget(self.session_sidebar)
        chat_splitter.addWidget(self.chat_page)
        chat_splitter.setSizes([252, 920])
        chat_layout.addWidget(chat_splitter)
        self.dataset_page = DatasetPage(self.api)
        self.training_page = TrainingPage(self.api)
        self.knowledge_page = KnowledgePage(self.api)
        self.agent_page = AgentPage(self.api, self.readiness_store)
        self.agent_workbench_page = AgentWorkbenchPage(self.api)
        self.agent_workbench_page.navigate_requested.connect(self._navigate_to)
        self.activity_page = ActivityPage(self.task_store)
        self.control_center_page = ControlCenterPage(self.api)
        self.developer_api_page = DeveloperApiPage(self.api)
        self.automation_page = AutomationPage(self.api)
        self.extensions_page = ExtensionsPage(self.api)
        self.settings_page = SettingsPage(
            self.api,
            APP_VERSION,
            lambda: self._check_for_updates(True),
            self.theme_manager,
            self.translator,
        )
        self._pages = {
            "overview": self.workspace_page,
            "chat": chat_surface,
            "models": self.models_page,
            "datasets": self.dataset_page,
            "training": self.training_page,
            "knowledge": self.knowledge_page,
            "agents": self.agent_page,
            "workbench": self.agent_workbench_page,
            "runtime": self.runtime_page,
            "activity": self.activity_page,
            "control": self.control_center_page,
            "developer": self.developer_api_page,
            "automation": self.automation_page,
            "extensions": self.extensions_page,
            "settings": self.settings_page,
        }
        for page in dict.fromkeys(self._pages.values()):
            self.stack.addWidget(page)
        self.task_center = TaskCenterDock(self.task_store, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.task_center)
        self.task_center.hide()
        self._init_command_menu()
        self._init_shortcuts()
        localize_tree(self, self.translator)
        self._navigate_to("overview")

        localize_tree(self, self.translator)

    def _retranslate(self, _locale: str) -> None:
        self.shell.retranslate()
        localize_tree(self, self.translator)
        self._navigate_to(self.active_destination)

    def _init_shortcuts(self) -> None:
        self.command_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_shortcut.activated.connect(self._open_command_palette)
        self.command_shortcut_mac = QShortcut(QKeySequence("Meta+K"), self)
        self.command_shortcut_mac.activated.connect(self._open_command_palette)

    def _open_command_palette(self) -> None:
        commands = [
            (
                self.translator.t("nav." + key, key.title()),
                "打开工作区",
                lambda destination=key: self._navigate_to(destination),
            )
            for key in (
                "overview",
                "chat",
                "models",
                "datasets",
                "training",
                "knowledge",
                "agents",
                "workbench",
                "automation",
                "developer",
                "control",
                "extensions",
                "activity",
                "runtime",
                "settings",
            )
        ]
        commands.extend(
            [
                ("新建对话", "开始新的对话", lambda: self._navigate_to("chat")),
                (
                    "检查更新",
                    "检查经过验证的 GitHub Release",
                    lambda: self._check_for_updates(True),
                ),
            ]
        )
        CommandPalette(commands, self).exec()

    def _init_command_menu(self) -> None:
        menu = self.menuBar()
        menu.setNativeMenuBar(False)
        menu.setVisible(True)
        command = menu.addMenu("命令")
        for title, key in (
            ("概览", "overview"),
            ("对话", "chat"),
            ("任务", "tasks"),
            ("运行时", "runtime"),
            ("开发者 API", "developer"),
            ("设置", "settings"),
        ):
            action = QAction(title, self)
            action.triggered.connect(
                lambda _checked=False, destination=key: self._navigate_to(destination)
            )
            command.addAction(action)
        command.addSeparator()
        updates = QAction("Check for updates…", self)
        updates.triggered.connect(lambda: self._check_for_updates(True))
        command.addAction(updates)
        models = menu.addMenu("模型")
        inventory = QAction("模型管理", self)
        inventory.triggered.connect(lambda: ModelCenterDialog(self.api, self).exec_())
        models.addAction(inventory)
        download = QAction("下载 GGUF 模型", self)
        download.triggered.connect(lambda: DownloadDialog(self.api, self).exec_())
        models.addAction(download)
        help_menu = menu.addMenu("帮助")
        about = QAction("关于 ModelForge", self)
        about.triggered.connect(
            lambda: QMessageBox.about(
                self,
                "ModelForge",
                f"<h3>MODEL FORGE {APP_VERSION}</h3><p>LOCAL AI WORKSTATION</p>",
            )
        )
        help_menu.addAction(about)

    def _navigate_to(self, destination: str) -> None:
        self.active_destination = destination
        self.shell.rail.set_active(destination)
        self.shell.topbar.set_page(
            self.translator.t(
                "nav." + destination,
                self.PAGE_TITLES.get(destination, destination).title(),
            )
        )
        if destination == "tasks":
            self._show_task_center()
        elif (page := self._pages.get(destination)) is not None:
            self.stack.setCurrentWidget(page)
        self.shell.set_status(
            "{} · {}".format(
                self.translator.t("nav." + destination, destination.title()),
                self.translator.t("footer.connected", "已连接 ModelForge 服务"),
            )
        )
        self._show_download_footer()

    def _on_session_selected(self, session_id: int) -> None:
        self.chat_page.set_session(session_id)
        self._navigate_to("chat")

    def _show_task_center(self) -> None:
        self.task_center.show()
        self.task_center.raise_()
        self.task_center.activateWindow()

    def _load_status(self) -> None:
        self.shell.set_status(self.translator.t("footer.connecting", "正在连接 ModelForge 服务…"))
        self._run_api(
            self.api.get_info, self._show_service_status, self._show_service_error
        )

    def _show_service_status(self, info: dict) -> None:
        _version = info.get("version", "Unavailable")
        self.shell.topbar.set_system(
            True, f"已登录：{self.api.username or '本地工作区'}"
        )
        self.shell.set_status(
            self.translator.t("footer.connected", "已连接 ModelForge 服务"),
            tooltip=str(self.api.base_url),
        )

    def _show_service_error(self, error: str) -> None:
        self.shell.topbar.set_system(False, "本地服务未连接")
        self.shell.set_status(f"无法连接服务：{error}")

    def _show_task_stream_status(self, online: bool, error: str) -> None:
        if online:
            # An active download owns the footer, but a broken task stream is a
            # failure signal and must not be hidden by the download progress bar.
            if self._show_download_footer():
                return
            self.shell.set_status(self.translator.t("footer.task_stream_connected", "任务更新已连接"))
        else:
            detail = str(error or "waiting")
            self.shell.set_status(
                self.translator.t("footer.task_stream_reconnecting", "正在重连任务更新…"),
                tooltip=detail,
            )

    def _latest_download_task(self) -> dict | None:
        downloads = [
            task for task in self.task_store.tasks.values()
            if task.get("source") == "model_download" or task.get("task_type") == "model_download"
        ]
        if not downloads:
            return None
        active_statuses = {"QUEUED", "RUNNING", "PAUSED", "CANCEL_REQUESTED"}
        active = [task for task in downloads if task.get("status") in active_statuses]
        candidates = active or [task for task in downloads if task.get("status") == "SUCCEEDED"] or downloads
        return max(candidates, key=lambda task: task.get("updated_at") or task.get("created_at") or "")

    def _download_path(self, task: dict | None) -> str:
        if not task:
            return ""
        result = task.get("result") or {}
        metadata = task.get("metadata") or {}
        return str(result.get("local_path") or metadata.get("local_path") or "")

    def _show_download_footer(self) -> bool:
        task = self._latest_download_task()
        if not task:
            return False
        status = task.get("status") or ""
        progress = int(task.get("progress_percent") or 0)
        repo = (task.get("metadata") or {}).get("repo_id") or task.get("title") or "模型"
        path = self._download_path(task)
        if status == "SUCCEEDED":
            self.shell.set_status(f"下载完成：{repo}", tooltip=path, progress=100)
            return True
        if status in {"QUEUED", "RUNNING", "PAUSED", "CANCEL_REQUESTED"}:
            label = {
                "QUEUED": "下载排队中",
                "RUNNING": "下载中",
                "PAUSED": "下载已暂停",
                "CANCEL_REQUESTED": "正在取消下载",
            }.get(status, "下载中")
            self.shell.set_status(f"{label}：{repo} · {progress}%", tooltip=path, progress=progress)
            return True
        return False

    def _open_download_footer_menu(self, position) -> None:
        task = self._latest_download_task()
        if not task:
            return
        menu = QMenu(self)
        open_panel = menu.addAction("打开下载界面")
        open_folder = menu.addAction("打开本地文件夹")
        sender = self.sender()
        anchor = sender if hasattr(sender, "mapToGlobal") else self.shell.footer_bar
        selected = menu.exec(anchor.mapToGlobal(position))
        if selected == open_panel:
            self._open_download_dialog(task.get("source_task_id"))
        elif selected == open_folder:
            self._open_download_folder(self._download_path(task))

    def _open_download_dialog(self, task_id: str | None = None) -> None:
        DownloadDialog(self.api, self, task_id=task_id).exec_()
        self.task_store.refresh()

    def _open_download_folder(self, local_path: str) -> None:
        if not local_path:
            QMessageBox.information(self, "下载目录", "还没有可打开的本地下载目录。")
            return
        path = Path(local_path)
        open_path = path if path.is_dir() else path.parent
        if not open_path.exists():
            QMessageBox.warning(self, "下载目录", f"本地目录不存在：\n{open_path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(open_path)))

    def _offer_recovery(self, restored: dict) -> None:
        if not self.recovery.previous_crash:
            return
        text = f"The previous session ended unexpectedly.\n{self.recovery.latest_crash_summary()}\n\nRestore the last workspace state?"
        if (
            QMessageBox.question(
                self,
                "恢复工作区",
                text,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            == QMessageBox.Yes
        ):
            session_id = restored.get("session_id")
            if isinstance(session_id, int):
                self.session_sidebar.current_session_id = session_id
                self.chat_page.set_session(session_id)

    def _check_for_updates(self, manual: bool) -> None:
        self._run_api(
            self.updater.check_latest,
            lambda update: self._update_checked(update, manual),
            lambda error: self._update_check_failed(error, manual),
        )

    def _update_checked(self, update: UpdateInfo | None, manual: bool) -> None:
        if update is None:
            if manual:
                QMessageBox.information(
                    self,
                    "Check updates",
                    "No verified release update is currently available.",
                )
            return
        if (
            QMessageBox.question(
                self,
                "Verified update",
                f"ModelForge {update.version} is available.\n\nThe download is SHA-256 verified before an installer is opened. Download now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            == QMessageBox.Yes
        ):
            self.shell.set_status(
                f"●  DOWNLOADING VERIFIED RELEASE  ·  {update.asset_name}"
            )
            self._run_api(
                lambda: self.updater.download_and_verify(update),
                self._update_downloaded,
                self._update_download_failed,
            )

    def _update_check_failed(self, error: str, manual: bool) -> None:
        if manual:
            QMessageBox.warning(self, "Check updates", format_api_error(error))

    def _update_downloaded(self, path: Path) -> None:
        if (
            QMessageBox.question(
                self,
                "Verified installer",
                f"SHA-256 verified installer:\n{path}\n\nOpen it now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            == QMessageBox.Yes
        ):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _update_download_failed(self, error: str) -> None:
        self.shell.set_status(f"●  UPDATE DOWNLOAD FAILED  ·  {format_api_error(error)}")
        QMessageBox.warning(self, "Update download", format_api_error(error))

    def closeEvent(self, event) -> None:
        self._update_check_timer.stop()
        self.readiness_store.shutdown()
        self.recovery.save_window_state(self)
        self.task_store.stop()
        self.chat_page.shutdown_stream()
        self.agent_page.timeline.shutdown_stream()
        # Every page owns background workers, and a page that is destroyed
        # while one of its workers still runs aborts the process. Shut down
        # all of them instead of a hand-maintained subset.
        for page in dict.fromkeys([self.session_sidebar, *self._pages.values(), self.task_center]):
            shutdown = getattr(page, "shutdown_async_api", None)
            if shutdown:
                shutdown()
        self.shutdown_async_api()
        super().closeEvent(event)


# A request that is still in flight when the window closes is detached from
# its page; give it a moment so the process can exit cleanly.
_EXIT_WORKER_GRACE_MS = 5000

# How long the window waits before the background update check runs. Keeping it
# as a module constant lets tests exercise the cancel-on-close path quickly.
_UPDATE_CHECK_DELAY_MS = 1800

# Qt teardown is not recoverable from Python: the window object graph keeps
# reference cycles that are only collected during interpreter shutdown, after
# `QApplication` is gone, which Qt turns into an access violation
# (0xC0000005). Set MODELFORGE_DEBUG_TEARDOWN=1 to keep Python's normal
# shutdown path when debugging that teardown itself.
_DEBUG_TEARDOWN_ENV = "MODELFORGE_DEBUG_TEARDOWN"


def _dispose_window(app, window) -> None:
    """Best-effort widget teardown while ``QApplication`` is still alive.

    Only used on the debug path: releasing the window object graph while the
    application exists avoids the access violation that happens when the cyclic
    collector frees it during interpreter shutdown.
    """
    if window is None:
        return
    try:
        window.hide()
        window.setParent(None)
        window.deleteLater()
        if app is not None:
            app.processEvents()
    except RuntimeError:  # already destroyed
        pass
    gc.collect()


def _exit_process(exit_code: int, *, app=None, window=None) -> int:
    """Leave the process deterministically instead of letting Qt tear down.

    The window is already closed at this point, so the only teardown left is
    the one that crashes. `os._exit` skips atexit handlers and logging
    teardown, so buffered diagnostics are flushed by hand first.
    """
    if os.environ.get(_DEBUG_TEARDOWN_ENV) == "1":
        # Keep Python's own shutdown for debugging, but do not hand Qt a live
        # window object graph: that is the crash we are working around.
        _dispose_window(app, window)
        return exit_code
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    logging.shutdown()
    os._exit(exit_code)


def main() -> int:
    app = QApplication(sys.argv)
    theme_manager = apply_theme(app)
    translator = I18n()
    recovery = RecoveryManager(APP_NAME)
    recovery.install_exception_hook()
    recovery.mark_started()
    api = ModelForgeClient()
    login = LoginDialog(api)
    if login.exec_() != LoginDialog.Accepted:
        recovery.mark_clean_exit()
        return 0
    window = MainWindow(api, recovery, translator, theme_manager)
    window.show()
    exit_code = app.exec()
    recovery.mark_clean_exit()
    if not wait_for_api_workers(_EXIT_WORKER_GRACE_MS):
        # A blocking socket call cannot be cancelled safely, so the thread is
        # still owned by the process-level holder; report it before leaving.
        log_pending_api_workers()
    return _exit_process(exit_code, app=app, window=window)


if __name__ == "__main__":
    raise SystemExit(main())
