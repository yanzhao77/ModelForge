"""Reusable widgets for the ModelForge Future AI Workstation."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class MFPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MFPanel")
        self.setProperty("panel", True)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 14, 16, 14)
        self.layout.setSpacing(10)


class MFSection(QWidget):
    def __init__(self, eyebrow: str, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.eyebrow = QLabel(eyebrow.upper())
        self.eyebrow.setProperty("role", "eyebrow")
        self.title = QLabel(title)
        self.title.setProperty("role", "pageTitle")
        layout.addWidget(self.eyebrow)
        layout.addWidget(self.title)


class MFPageHeader(QWidget):
    """Shared page header: one title, optional subtitle, status and primary action."""

    def __init__(self, title: str, subtitle: str = "", status: QWidget | None = None, action: QWidget | None = None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self.title = QLabel(title)
        self.title.setProperty("role", "pageTitle")
        title_row.addWidget(self.title)
        self.status = status
        if status is not None:
            title_row.addWidget(status)
        title_row.addStretch(1)
        copy.addLayout(title_row)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        copy.addWidget(self.subtitle)
        layout.addLayout(copy, 1)
        self.action = action
        if action is not None:
            layout.addWidget(action, 0)

    def set_text(self, title: str, subtitle: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))


class MFPageToolbar(QFrame):
    """Single-row toolbar that keeps search/filter/actions aligned."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("toolbar", True)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)

    def add_stretch(self) -> None:
        self.layout.addStretch(1)


class MFSettingsRow(QFrame):
    """macOS-style setting row with label, optional detail and trailing control."""

    def __init__(self, label: str, detail: str = "", control: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.setProperty("settingsRow", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(16)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(3)
        self.label = QLabel(label)
        self.label.setProperty("role", "sectionTitle")
        self.detail = QLabel(detail)
        self.detail.setProperty("role", "muted")
        self.detail.setWordWrap(True)
        self.detail.setVisible(bool(detail))
        copy.addWidget(self.label)
        copy.addWidget(self.detail)
        layout.addLayout(copy, 1)
        self.control = control
        if control is not None:
            control.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            layout.addWidget(control, 0)

    def set_text(self, label: str, detail: str = "") -> None:
        self.label.setText(label)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))


class MFMetric(QFrame):
    def __init__(self, label: str, value: str = "Unavailable", detail: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("MFPanel")
        self.setProperty("panel", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self.label = QLabel(label.upper())
        self.label.setProperty("role", "eyebrow")
        self.value = QLabel(value)
        self.value.setProperty("role", "metric")
        self.detail = QLabel(detail)
        self.detail.setProperty("role", "muted")
        self.detail.setWordWrap(True)
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_value(self, value: str, detail: str = "") -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class MFStatusBadge(QFrame):
    COLORS = {"online": "online", "ready": "online", "running": "online", "warning": "warning", "failed": "error", "error": "error", "offline": "error"}

    def __init__(self, text: str, state: str = "warning", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.dot = QLabel("●")
        self.label = QLabel(text)
        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        self.set_state(text, state)

    def set_state(self, text: str, state: str) -> None:
        role = self.COLORS.get(state.lower(), "warning")
        self.dot.setProperty("status", role)
        self.label.setProperty("status", role)
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)
        self.label.setText(text)


class MFEmptyState(MFPanel):
    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.layout.setAlignment(Qt.AlignCenter)
        title_label = QLabel(title)
        title_label.setProperty("role", "sectionTitle")
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignCenter)
        detail_label = QLabel(detail)
        detail_label.setAlignment(Qt.AlignCenter)
        detail_label.setWordWrap(True)
        self.layout.addWidget(title_label)
        self.layout.addWidget(detail_label)


class _EmptyStateWatcher(QObject):
    """Keeps an MFEmptyState overlay sized to its host view's viewport."""

    def __init__(self, view: QAbstractItemView, overlay: MFEmptyState):
        super().__init__(view)
        self._view = view
        self._overlay = overlay
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._view.viewport() and event.type() == QEvent.Resize:
            self._overlay.setGeometry(self._view.viewport().rect())
        return False


def install_empty_state(view: QAbstractItemView, title: str, detail: str):
    """Overlay an MFEmptyState on a list/table; returns a set_empty(bool) toggle.

    The view stays in its existing layout; the overlay lives in the viewport,
    so callers only flip visibility when data arrives.
    """
    overlay = MFEmptyState(title, detail, view.viewport())
    overlay.hide()
    watcher = _EmptyStateWatcher(view, overlay)
    view._mf_empty_overlay = overlay

    def set_empty(empty: bool) -> None:
        overlay.setGeometry(view.viewport().rect())
        overlay.setVisible(empty)

    return set_empty, watcher
