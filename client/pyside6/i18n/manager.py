"""JSON-backed translator with Simplified Chinese as the product default."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal
from .ui_localizer import set_current


class I18n(QObject):
    changed = Signal(str)
    SUPPORTED = ("zh_CN", "en_US", "ja_JP")
    DEFAULT_LOCALE = "zh_CN"
    _PREFERENCE_VERSION = 2

    def __init__(self, base_dir: Path | None = None):
        super().__init__()
        self.base_dir = Path(base_dir or Path(__file__).parent)
        self.settings = QSettings("ModelForge", "Desktop")
        migrated = self.settings.value("language/preference_version", 0, type=int)
        saved = self.settings.value("language/locale", "", type=str)
        # Migrate an older system-language default once, then preserve explicit choices.
        if migrated < self._PREFERENCE_VERSION or saved not in self.SUPPORTED:
            saved = self.DEFAULT_LOCALE
            self.settings.setValue("language/locale", saved)
            self.settings.setValue("language/preference_version", self._PREFERENCE_VERSION)
        self.locale = saved
        self._messages = self._load(self.locale)

        set_current(self)
    def _load(self, name: str) -> dict:
        try:
            return json.loads((self.base_dir / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_locale(self, name: str) -> None:
        if name not in self.SUPPORTED:
            return
        self.locale, self._messages = name, self._load(name)
        self.settings.setValue("language/locale", name)
        self.settings.setValue("language/preference_version", self._PREFERENCE_VERSION)
        self.changed.emit(name)

    def t(self, key: str, default: str | None = None) -> str:
        return self._messages.get(key, default or key)
