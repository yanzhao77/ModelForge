from __future__ import annotations

from components.mf.primitives import MFStatusBadge
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from theme.icons import glyph
from theme.metrics import SIDEBAR_COLLAPSED_WIDTH, SIDEBAR_WIDTH, TOPBAR_HEIGHT


class NavigationRail(QFrame):
    """Grouped navigation that collapses automatically on narrow desktop windows."""

    destination_requested = Signal(str)
    GROUPS = (
        ("nav_group.workspace", ("overview", "chat", "models", "datasets", "training", "knowledge", "agents", "workbench")),
        ("nav_group.operations", ("automation", "tasks", "runtime")),
        ("nav_group.administration", ("developer", "control", "extensions", "settings")),
    )

    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.setObjectName("SideRail")
        self._collapsed = False
        self._buttons: dict[str, QPushButton] = {}
        self._group_labels: list[tuple[str, QLabel]] = []
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 16, 12, 14)
        self.layout.setSpacing(3)
        self.brand = QLabel("ModelForge")
        self.brand.setStyleSheet("font-size: 16px; font-weight: 650;")
        self.layout.addWidget(self.brand)
        self.toggle = QPushButton("收起导航")
        self.toggle.setObjectName("NavigationToggle")
        self.toggle.setAccessibleName("展开或收起导航")
        self.toggle.setToolTip("展开或收起导航")
        self.toggle.clicked.connect(self.toggle_collapsed)
        self.layout.addWidget(self.toggle)
        self.layout.addSpacing(10)
        self._build()
        self.layout.addStretch(1)
        self.user = QLabel("本地工作区")
        self.user.setProperty("role", "muted")
        self.layout.addWidget(self.user)
        self.set_collapsed(False)

    def _build(self) -> None:
        for group_index, (group_key, entries) in enumerate(self.GROUPS):
            if group_index:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet("margin: 8px 4px;")
                self.layout.addWidget(line)
            label = QLabel(self.translator.t(group_key, group_key))
            label.setProperty("role", "eyebrow")
            self.layout.addWidget(label)
            self._group_labels.append((group_key, label))
            for entry in entries:
                button = QPushButton()
                button.setCheckable(True)
                button.setCursor(Qt.PointingHandCursor)
                button.setProperty("nav", True)
                button.clicked.connect(lambda _checked=False, key=entry: self.destination_requested.emit(key))
                self.layout.addWidget(button)
                self._buttons[entry] = button
        self._update_button_text()

    def _update_button_text(self) -> None:
        for key, button in self._buttons.items():
            label = self.translator.t("nav." + key, key.title())
            button.setText(glyph(key) if self._collapsed else f"{glyph(key)}  {label}")
            button.setToolTip(label)
            button.setAccessibleName(label)
        self.toggle.setText("»" if self._collapsed else "收起导航")

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        if self._collapsed == collapsed and self.width() in {SIDEBAR_WIDTH, SIDEBAR_COLLAPSED_WIDTH}:
            return
        self._collapsed = collapsed
        self.setFixedWidth(SIDEBAR_COLLAPSED_WIDTH if collapsed else SIDEBAR_WIDTH)
        self.brand.setText("MF" if collapsed else "ModelForge")
        self.brand.setAlignment(Qt.AlignCenter if collapsed else Qt.AlignLeft)
        for _key, label in self._group_labels:
            label.setVisible(not collapsed)
        self.user.setVisible(not collapsed)
        self._update_button_text()

    def retranslate(self) -> None:
        for group_key, label in self._group_labels:
            label.setText(self.translator.t(group_key, group_key))
        self._update_button_text()

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
        self.identity = QLabel("尚未连接工作区")
        self.identity.setProperty("role", "muted")
        layout.addWidget(self.identity)
        self.status = MFStatusBadge("正在检查服务", "warning")
        layout.addWidget(self.status)

    def set_page(self, title: str) -> None:
        self.page.setText(title)

    def set_system(self, online: bool, identity: str = "") -> None:
        self.status.set_state("服务已连接" if online else "服务不可用", "online" if online else "error")
        self.identity.setText(identity or ("已连接工作区" if online else "请检查本地服务"))


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
        self.rail_scroll = QScrollArea()
        self.rail_scroll.setObjectName("NavigationScroll")
        self.rail_scroll.setFrameShape(QFrame.NoFrame)
        self.rail_scroll.setWidgetResizable(False)
        self.rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rail_scroll.setWidget(self.rail)
        body.addWidget(self.rail_scroll)
        self.content = QFrame()
        self.content.setObjectName("ContentSurface")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(32, 26, 32, 26)
        body.addWidget(self.content, 1)
        layout.addLayout(body, 1)
        self.footer = QLabel("正在准备工作区…")
        self.footer.setProperty("role", "muted")
        self.footer.setContentsMargins(18, 5, 18, 6)
        layout.addWidget(self.footer)
        self.rail_scroll.setFixedWidth(self.rail.width())

    def resizeEvent(self, event) -> None:
        self.rail.set_collapsed(self.width() < 1120)
        self.rail_scroll.setFixedWidth(self.rail.width())
        super().resizeEvent(event)

    def retranslate(self) -> None:
        self.rail.retranslate()

    def set_status(self, text: str) -> None:
        self.footer.setText(text)
