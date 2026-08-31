"""Minimal AI-native application shell for ModelForge."""
from __future__ import annotations

from components.mf.primitives import MFStatusBadge
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from theme.icons import glyph
from theme.tokens import SIDEBAR_WIDTH, TOPBAR_HEIGHT


class NavigationRail(QFrame):
    destination_requested = Signal(str)
    ORDER = ("overview", "chat", "models", "datasets", "training", "knowledge", "agents", "workbench", "automation", "control", "extensions", "separator", "tasks", "runtime", "separator", "settings")

    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.setObjectName("SideRail")
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._buttons: dict[str, QPushButton] = {}
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 16, 12, 14)
        self.layout.setSpacing(3)
        self.brand = QLabel("ModelForge")
        self.brand.setStyleSheet("font-size: 16px; font-weight: 650;")
        self.layout.addWidget(self.brand)
        self.layout.addSpacing(18)
        self._build()
        self.layout.addStretch(1)
        self.user = QLabel("本地工作区")
        self.user.setProperty("role", "muted")
        self.layout.addWidget(self.user)

    def _build(self) -> None:
        for entry in self.ORDER:
            if entry == "separator":
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet("margin: 10px 4px;")
                self.layout.addWidget(line)
                continue
            button = QPushButton(f"{glyph(entry)}  {self.translator.t('nav.' + entry)}")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("nav", True)
            button.clicked.connect(lambda _checked=False, key=entry: self.destination_requested.emit(key))
            self.layout.addWidget(button)
            self._buttons[entry] = button

    def retranslate(self) -> None:
        for key, button in self._buttons.items():
            button.setText(f"{glyph(key)}  {self.translator.t('nav.' + key)}")

    def set_active(self, key: str) -> None:
        for item_key, button in self._buttons.items():
            button.setChecked(item_key == key)


class TopContext(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(TOPBAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 8, 22, 8)
        self.page = QLabel("首页")
        self.page.setProperty("role", "pageTitle")
        layout.addWidget(self.page)
        layout.addStretch(1)
        self.model = QLabel("未选择模型")
        self.model.setProperty("role", "muted")
        layout.addWidget(self.model)
        self.status = MFStatusBadge("Checking connection", "warning")
        layout.addWidget(self.status)

    def set_page(self, title: str) -> None:
        self.page.setText(title)

    def set_system(self, online: bool, detail: str = "") -> None:
        self.status.set_state("就绪" if online else "服务不可用", "online" if online else "error")
        self.model.setText(detail or ("Connected" if online else "Check ModelForge Server"))


class AppShell(QWidget):
    destination_requested = Signal(str)
    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.setObjectName("AppShell")
        self.translator = translator
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.topbar = TopContext()
        layout.addWidget(self.topbar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.rail = NavigationRail(translator)
        self.rail.destination_requested.connect(self.destination_requested)
        body.addWidget(self.rail)
        self.content = QFrame()
        self.content.setObjectName("ContentSurface")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(32, 26, 32, 26)
        body.addWidget(self.content, 1)
        layout.addLayout(body, 1)
        self.footer = QLabel("正在连接 ModelForge 服务…")
        self.footer.setProperty("role", "muted")
        self.footer.setContentsMargins(18, 5, 18, 6)
        layout.addWidget(self.footer)

    def retranslate(self) -> None:
        self.rail.retranslate()

    def set_status(self, text: str, tooltip: str | None = None) -> None:
        self.footer.setText(text)
        self.footer.setToolTip(tooltip or "")
