from __future__ import annotations

from components.mf.primitives import MFStatusBadge
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from theme.icons import icon
from theme.metrics import (
    PAGE_MARGIN,
    PAGE_MARGIN_NARROW,
    SIDEBAR_COLLAPSED_WIDTH,
    SIDEBAR_WIDTH,
    TOPBAR_HEIGHT,
)


class NavigationRail(QFrame):
    """Grouped navigation that collapses automatically on narrow desktop windows."""

    destination_requested = Signal(str)
    GROUPS = (
        ("nav_group.workspace", ("overview", "dashboard", "chat", "models", "videos", "datasets", "training", "knowledge", "agents", "workbench", "workflows")),
        ("nav_group.operations", ("automation", "runtime")),
        ("nav_group.administration", ("developer", "control", "tasks", "extensions", "settings")),
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
        self.brand.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.layout.addWidget(self.brand)
        self.toggle = QPushButton(self.translator.t("shell.nav.collapse", "收起导航"))
        self.toggle.setObjectName("NavigationToggle")
        self.toggle.setAccessibleName(self.translator.t("shell.nav.toggle", "展开或收起导航"))
        self.toggle.setToolTip(self.translator.t("shell.nav.toggle", "展开或收起导航"))
        self.toggle.clicked.connect(self.toggle_collapsed)
        self.layout.addWidget(self.toggle)
        self.layout.addSpacing(10)
        self._build()
        self.layout.addStretch(1)
        self.user = QLabel(self.translator.t("shell.workspace.local", "本地工作区"))
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
                button.setIconSize(button.iconSize())
                button.clicked.connect(lambda _checked=False, key=entry: self.destination_requested.emit(key))
                self.layout.addWidget(button)
                self._buttons[entry] = button
        self._update_button_text()

    def _update_button_text(self) -> None:
        for key, button in self._buttons.items():
            label = self.translator.t("nav." + key, key.title())
            button.setIcon(icon(key))
            button.setText("" if self._collapsed else label)
            button.setToolTip(label)
            button.setAccessibleName(label)
        self.toggle.setText("»" if self._collapsed else self.translator.t("shell.nav.collapse", "收起导航"))

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
        self.user.setText(self.translator.t("shell.workspace.local", "本地工作区"))
        self.toggle.setAccessibleName(self.translator.t("shell.nav.toggle", "展开或收起导航"))
        self.toggle.setToolTip(self.translator.t("shell.nav.toggle", "展开或收起导航"))
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
        self.page = QLabel("")
        self.page.setProperty("role", "pageTitle")
        layout.addWidget(self.page)
        layout.addStretch(1)
        self.identity = QLabel("")
        self.identity.setProperty("role", "muted")
        layout.addWidget(self.identity)
        self.status = MFStatusBadge("", "warning")
        layout.addWidget(self.status)

    def set_page(self, title: str) -> None:
        self.page.setText(title)

    def set_system(self, online: bool, identity: str = "", translator=None) -> None:
        t = translator.t if translator is not None else (lambda _key, default=None: default or _key)
        self.status.set_state(t("shell.service.connected" if online else "shell.service.unavailable", "服务已连接" if online else "服务不可用"), "online" if online else "error")
        self.identity.setText(identity or t("shell.workspace.connected" if online else "shell.workspace.check_service", "已连接工作区" if online else "请检查本地服务"))

    def set_authentication_required(self, translator=None) -> None:
        t = translator.t if translator is not None else (lambda _key, default=None: default or _key)
        self.identity.setText(t("status.login_required", "需要登录"))
        self.status.set_state(t("shell.session.expired", "会话已失效"), "error")


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
        self.content_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        body.addWidget(self.content, 1)
        layout.addLayout(body, 1)
        self.footer_bar = QFrame()
        self.footer_bar.setObjectName("FooterBar")
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(18, 5, 18, 6)
        footer_layout.setSpacing(10)
        self.footer = QLabel(translator.t("shell.workspace.preparing", "正在准备工作区…"))
        self.footer.setProperty("role", "muted")
        footer_layout.addWidget(self.footer, 1)
        self.footer_progress = QProgressBar()
        self.footer_progress.setRange(0, 100)
        self.footer_progress.setFixedWidth(180)
        self.footer_progress.setTextVisible(True)
        self.footer_progress.hide()
        footer_layout.addWidget(self.footer_progress)
        layout.addWidget(self.footer_bar)
        self.rail_scroll.setFixedWidth(self.rail.width())

    def resizeEvent(self, event) -> None:
        narrow = self.width() < 1120
        self.rail.set_collapsed(narrow)
        margin = PAGE_MARGIN_NARROW if narrow else PAGE_MARGIN
        self.content_layout.setContentsMargins(margin, margin, margin, margin)
        self.rail_scroll.setFixedWidth(self.rail.width())
        super().resizeEvent(event)

    def retranslate(self) -> None:
        self.rail.retranslate()

    def set_status(self, text: str, tooltip: str | None = None, progress: int | None = None) -> None:
        self.footer.setText(text)
        self.footer.setToolTip(tooltip or "")
        self.footer_bar.setToolTip(tooltip or "")
        if progress is None:
            self.footer_progress.hide()
            return
        self.footer_progress.setValue(max(0, min(100, int(progress))))
        self.footer_progress.show()
