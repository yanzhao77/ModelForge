import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client" / "pyside6"
if str(CLIENT) not in sys.path:
    sys.path.insert(0, str(CLIENT))
from i18n.ui_localizer import text


def test_core_ui_text_has_all_three_locales():
    assert text("设置", "zh_CN") == "设置"
    assert text("设置", "en_US") == "Settings"
    assert text("设置", "ja_JP") == "設定"
    assert text("开始对话", "en_US") == "Start Chat"
    assert text("管理远程模型", "ja_JP") == "リモートモデルを管理"
