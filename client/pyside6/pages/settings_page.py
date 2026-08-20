"""Modern settings workspace for appearance, language, connection and updates."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QListWidget, QStackedWidget, QPushButton, QVBoxLayout, QWidget

from components.mf.primitives import MFPanel, MFSection, MFStatusBadge


class SettingsPage(QWidget):
    def __init__(self, api, version: str, check_updates, theme_manager, translator, parent=None):
        super().__init__(parent)
        self.api, self.version, self.check_updates = api, version, check_updates
        self.theme_manager, self.translator = theme_manager, translator
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(MFSection("偏好设置", "设置"))
        body = QHBoxLayout()
        self.categories = QListWidget()
        self.categories.setFixedWidth(168)
        for item in ("通用", "外观", "语言", "服务连接", "关于"):
            self.categories.addItem(item)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._general())
        self.pages.addWidget(self._appearance())
        self.pages.addWidget(self._language())
        self.pages.addWidget(self._backend())
        self.pages.addWidget(self._about())
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(0)
        body.addWidget(self.categories)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

    def _page(self, title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 0, 0, 0)
        heading = QLabel(title)
        heading.setProperty("role", "pageTitle")
        layout.addWidget(heading)
        detail = QLabel(description)
        detail.setProperty("role", "muted")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        return page, layout

    def _general(self) -> QWidget:
        page, layout = self._page("通用", "管理当前 ModelForge 本地工作区的默认设置。")
        panel = MFPanel()
        panel.layout.addWidget(QLabel("工作区"))
        note = QLabel("对话、模型和任务将继续连接到本机 ModelForge 服务。")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        panel.layout.addWidget(note)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _appearance(self) -> QWidget:
        page, layout = self._page("外观", "选择界面主题，不会影响当前工作内容。")
        panel = MFPanel()
        row = QHBoxLayout()
        row.addWidget(QLabel("主题"))
        row.addStretch(1)
        self.theme_select = QComboBox()
        self.theme_select.addItem("浅色", "light")
        self.theme_select.addItem("深色", "dark")
        self.theme_select.addItem("跟随系统", "system")
        index = self.theme_select.findData(self.theme_manager.mode.value)
        self.theme_select.setCurrentIndex(max(index, 0))
        self.theme_select.currentIndexChanged.connect(lambda _: self.theme_manager.set_mode(self.theme_select.currentData()))
        row.addWidget(self.theme_select)
        panel.layout.addLayout(row)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _language(self) -> QWidget:
        page, layout = self._page("语言", "为导航和已适配的产品界面选择显示语言。")
        panel = MFPanel()
        row = QHBoxLayout()
        row.addWidget(QLabel("显示语言"))
        row.addStretch(1)
        self.language_select = QComboBox()
        self.language_select.addItem("简体中文", "zh_CN")
        self.language_select.addItem("English", "en_US")
        self.language_select.addItem("日本語", "ja_JP")
        index = self.language_select.findData(self.translator.locale)
        self.language_select.setCurrentIndex(max(index, 0))
        self.language_select.currentIndexChanged.connect(lambda _: self.translator.set_locale(self.language_select.currentData()))
        row.addWidget(self.language_select)
        panel.layout.addLayout(row)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _backend(self) -> QWidget:
        page, layout = self._page("服务连接", "查看当前本地工作区使用的服务连接。")
        panel = MFPanel()
        self.connection = MFStatusBadge("已连接" if self.api and self.api.username else "需要登录", "online" if self.api and self.api.username else "warning")
        panel.layout.addWidget(self.connection)
        endpoint = QLabel(f"Endpoint  {self.api.base_url}\nAccount   {self.api.username or 'Unavailable'}")
        endpoint.setProperty("role", "muted")
        panel.layout.addWidget(endpoint)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _about(self) -> QWidget:
        page, layout = self._page("关于", "通过经过验证的 GitHub Release 获取 ModelForge 更新。")
        panel = MFPanel()
        panel.layout.addWidget(QLabel(f"ModelForge {self.version}"))
        info = QLabel("安装包将在打开前通过 SHA-256 清单验证完整性。")
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        panel.layout.addWidget(info)
        check = QPushButton("检查更新")
        check.clicked.connect(self.check_updates)
        panel.layout.addWidget(check)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page
