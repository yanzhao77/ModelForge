"""Persistent Light / Dark / System theme preference management."""
from __future__ import annotations
from enum import Enum
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QGuiApplication
from .tokens import DARK, LIGHT

class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"

class ThemeManager(QObject):
    changed = Signal(str)
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = QSettings("ModelForge", "Desktop")
        self.mode = ThemeMode(self.settings.value("appearance/theme", ThemeMode.SYSTEM.value))
    def effective_mode(self) -> ThemeMode:
        if self.mode != ThemeMode.SYSTEM:
            return self.mode
        hints = QGuiApplication.styleHints()
        return ThemeMode.DARK if hints.colorScheme().name.lower() == "dark" else ThemeMode.LIGHT
    def palette(self) -> dict:
        return DARK if self.effective_mode() == ThemeMode.DARK else LIGHT
    def apply(self) -> None:
        from .theme import application_stylesheet
        self.app.setStyleSheet(application_stylesheet(self.palette()))
        self.changed.emit(self.effective_mode().value)
    def set_mode(self, mode: str) -> None:
        self.mode = ThemeMode(mode)
        self.settings.setValue("appearance/theme", self.mode.value)
        self.apply()
