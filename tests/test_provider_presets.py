"""Offscreen preset coverage for the remote provider dialog.

The dialog is the desktop surface where users configure OpenAI-compatible
remote providers; named presets fill name/base_url/model so a provider is
used as a first-class service instead of an anonymous custom base URL.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from components.provider_dialog import RemoteProviderDialog
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _dialog() -> RemoteProviderDialog:
    api = MagicMock()
    api.list_remote_providers.return_value = []
    return RemoteProviderDialog(api)


def test_orcarouter_preset_is_listed():
    dialog = _dialog()
    try:
        presets = [dialog.preset.itemData(index) for index in range(dialog.preset.count())]
        assert "orcarouter" in presets
    finally:
        dialog.shutdown_async_api()


def test_orcarouter_preset_fills_named_provider_fields():
    dialog = _dialog()
    try:
        dialog.preset.setCurrentIndex(dialog.preset.findData("orcarouter"))
        assert dialog.name.text() == "OrcaRouter"
        assert dialog.base_url.text() == "https://api.orcarouter.ai/v1"
        assert dialog.model.text() == "orcarouter/auto"
        assert dialog.protocol.currentData() == "responses"
    finally:
        dialog.shutdown_async_api()


def test_openai_preset_is_preserved():
    dialog = _dialog()
    try:
        dialog.preset.setCurrentIndex(dialog.preset.findData("openai"))
        assert dialog.name.text() == "OpenAI"
        assert dialog.base_url.text() == "https://api.openai.com/v1"
        assert dialog.model.text() == "gpt-4.1-mini"
    finally:
        dialog.shutdown_async_api()
