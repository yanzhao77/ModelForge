"""Global stylesheet generator for ModelForge Modern AI-Native UI."""

from __future__ import annotations

from . import tokens as t


def application_stylesheet(p: dict) -> str:
    return f"""
    * {{ font-family: {t.FONT_UI}; color: {p["text"]}; }}
    QMainWindow, QDialog, QWidget#AppShell {{ background: {p["bg"]}; }}
    QWidget#TopBar {{ background: {p["surface"]}; border-bottom: 1px solid {p["border"]}; }}
    QWidget#SideRail {{ background: {p["surface"]}; border-right: 1px solid {p["border"]}; }}
    QWidget#ContentSurface {{ background: {p["bg"]}; }}
    QFrame[panel="true"], QWidget#MFPanel, QGroupBox {{ background: {p["surface"]}; border: 1px solid {p["border"]}; border-radius: {t.RADIUS_MD}px; }}
    QGroupBox {{ margin-top: 12px; padding: 13px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p["muted"]}; font-size: 11px; }}
    QLabel {{ background: transparent; }}
    QLabel[role="eyebrow"] {{ color: {p["muted"]}; font-size: 11px; font-weight: 600; letter-spacing: 0.4px; }}
    QLabel[role="pageTitle"] {{ color: {p["text"]}; font-size: 24px; font-weight: 650; }}
    QLabel[role="metric"] {{ font-family: {t.FONT_MONO}; font-size: 17px; font-weight: 600; }}
    QLabel[role="muted"] {{ color: {p["muted"]}; }}
    QLabel[status="online"] {{ color: {p["success"]}; }} QLabel[status="warning"] {{ color: {p["warning"]}; }} QLabel[status="error"] {{ color: {p["danger"]}; }}
    QPushButton {{ background: {p["surface"]}; border: 1px solid {p["border_strong"]}; border-radius: {t.RADIUS_SM}px; padding: 7px 12px; min-height: 18px; font-weight: 550; }}
    QPushButton:hover {{ background: {p["hover"]}; }} QPushButton:pressed {{ background: {p["selection"]}; }}
    QPushButton:disabled {{ color: {p["dim"]}; border-color: {p["border"]}; }}
    QPushButton[accent="true"] {{ background: {p["accent"]}; color: {p["accent_fg"]}; border-color: {p["accent"]}; }}
    QPushButton[nav="true"] {{ text-align: left; color: {p["muted"]}; background: transparent; border: 1px solid transparent; padding: 8px 10px; font-size: 12px; font-weight: 500; }}
    QPushButton[nav="true"]:hover {{ color: {p["text"]}; background: {p["hover"]}; }}
    QPushButton[nav="true"]:checked {{ color: {p["text"]}; background: {p["selection"]}; border-color: transparent; font-weight: 600; }}
    QLineEdit, QTextEdit, QTextBrowser, QPlainTextEdit, QComboBox {{ background: {p["surface"]}; border: 1px solid {p["border_strong"]}; border-radius: {t.RADIUS_SM}px; padding: 8px 10px; selection-background-color: {p["selection"]}; }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {p["text"]}; }}
    QTableWidget, QListWidget, QTreeWidget {{ background: {p["surface"]}; alternate-background-color: {p["surface_subtle"]}; border: 1px solid {p["border"]}; outline: 0; }}
    QTableWidget::item, QListWidget::item {{ padding: 8px; border-bottom: 1px solid {p["border"]}; }}
    QTableWidget::item:selected, QListWidget::item:selected {{ background: {p["selection"]}; color: {p["text"]}; }}
    QHeaderView::section {{ background: {p["surface_subtle"]}; color: {p["muted"]}; border: 0; border-bottom: 1px solid {p["border"]}; padding: 8px; font-size: 11px; font-weight: 600; }}
    QProgressBar {{ background: {p["surface_subtle"]}; border: 0; border-radius: 3px; height: 6px; color: transparent; }} QProgressBar::chunk {{ background: {p["text"]}; border-radius: 3px; }}
    QMenuBar {{ background: {p["surface"]}; border-bottom: 1px solid {p["border"]}; }} QMenuBar::item {{ padding: 5px 8px; color: {p["muted"]}; }} QMenuBar::item:selected {{ background: {p["hover"]}; color: {p["text"]}; }}
    QMenu {{ background: {p["surface"]}; border: 1px solid {p["border"]}; padding: 4px; }} QMenu::item {{ padding: 7px 24px 7px 12px; }} QMenu::item:selected {{ background: {p["hover"]}; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; }} QScrollBar::handle:vertical {{ background: {p["border_strong"]}; border-radius: 4px; min-height: 28px; }}
    """


def apply_theme(app):
    from .theme_manager import ThemeManager

    manager = ThemeManager(app)
    manager.apply()
    return manager
