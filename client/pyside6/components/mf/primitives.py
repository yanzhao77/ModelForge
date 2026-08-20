"""Reusable widgets for the ModelForge Future AI Workstation."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


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
        title_label.setProperty("role", "pageTitle")
        detail_label = QLabel(detail)
        detail_label.setAlignment(Qt.AlignCenter)
        detail_label.setWordWrap(True)
        self.layout.addWidget(title_label)
        self.layout.addWidget(detail_label)
