"""Semantic line icons for the desktop client.

The public entrypoint is ``icon(name)``.  Icons are drawn as Qt vector-ish
pixmaps so the desktop client has one consistent source for navigation and
tool buttons without depending on a web-only icon package at runtime.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


_ALIASES = {
    "overview": "home",
    "dashboard": "home",
    "chat": "message-square",
    "models": "box",
    "videos": "play",
    "datasets": "database",
    "training": "sliders",
    "knowledge": "book-open",
    "agents": "bot",
    "workbench": "bot",
    "workflows": "workflow",
    "automation": "workflow",
    "tasks": "list-todo",
    "runtime": "activity",
    "activity": "activity",
    "developer": "terminal",
    "control": "layout-dashboard",
    "extensions": "plug",
    "settings": "settings",
    "online": "activity",
    "refresh": "refresh",
    "search": "search",
    "folder": "folder",
    "send": "send",
    "stop": "square",
}


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#596270", size: int = 18) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), max(1.6, size / 11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    _draw(painter, _ALIASES.get(name, name), size)
    painter.end()
    return QIcon(pixmap)


def glyph(_name: str, fallback: str = "") -> str:
    """Compatibility shim for older code that still expects text icons."""
    return fallback


def _draw(p: QPainter, name: str, s: int) -> None:
    x = s / 24
    r = lambda a, b, c, d: QRectF(a * x, b * x, c * x, d * x)
    line = lambda a, b, c, d: p.drawLine(QPointF(a * x, b * x), QPointF(c * x, d * x))
    if name == "home":
        path = QPainterPath(QPointF(4 * x, 11 * x))
        path.lineTo(12 * x, 4 * x)
        path.lineTo(20 * x, 11 * x)
        p.drawPath(path)
        p.drawRect(r(6.5, 10.5, 11, 9))
        line(10, 19.5, 10, 14)
        line(14, 19.5, 14, 14)
    elif name == "message-square":
        p.drawRoundedRect(r(4, 5, 16, 12), 3 * x, 3 * x)
        line(8, 17, 7, 21)
        line(7, 21, 12, 17)
    elif name == "box":
        p.drawPolygon([QPointF(12*x, 3*x), QPointF(20*x, 7*x), QPointF(12*x, 11*x), QPointF(4*x, 7*x)])
        p.drawPolygon([QPointF(4*x, 7*x), QPointF(12*x, 11*x), QPointF(12*x, 21*x), QPointF(4*x, 17*x)])
        p.drawPolygon([QPointF(20*x, 7*x), QPointF(12*x, 11*x), QPointF(12*x, 21*x), QPointF(20*x, 17*x)])
    elif name == "database":
        p.drawEllipse(r(5, 4, 14, 5))
        p.drawArc(r(5, 8, 14, 5), 180 * 16, 180 * 16)
        p.drawArc(r(5, 14, 14, 5), 180 * 16, 180 * 16)
        line(5, 6.5, 5, 16.5)
        line(19, 6.5, 19, 16.5)
    elif name == "book-open":
        p.drawRoundedRect(r(4, 5, 7, 14), 1.5 * x, 1.5 * x)
        p.drawRoundedRect(r(13, 5, 7, 14), 1.5 * x, 1.5 * x)
        line(12, 7, 12, 20)
    elif name == "bot":
        p.drawRoundedRect(r(5, 8, 14, 10), 3 * x, 3 * x)
        line(12, 8, 12, 4)
        p.drawEllipse(r(10.8, 2.8, 2.4, 2.4))
        p.drawPoint(QPointF(9 * x, 13 * x)); p.drawPoint(QPointF(15 * x, 13 * x))
        line(9, 17, 15, 17)
    elif name == "workflow":
        p.drawRoundedRect(r(4, 5, 5, 5), 1.5 * x, 1.5 * x)
        p.drawRoundedRect(r(15, 5, 5, 5), 1.5 * x, 1.5 * x)
        p.drawRoundedRect(r(9.5, 15, 5, 5), 1.5 * x, 1.5 * x)
        line(9, 7.5, 15, 7.5); line(12, 10, 12, 15)
    elif name == "sliders":
        line(4, 7, 20, 7); line(4, 12, 20, 12); line(4, 17, 20, 17)
        p.drawEllipse(r(8, 5.2, 3.6, 3.6)); p.drawEllipse(r(14, 10.2, 3.6, 3.6)); p.drawEllipse(r(6, 15.2, 3.6, 3.6))
    elif name == "list-todo":
        line(10, 7, 20, 7); line(10, 12, 20, 12); line(10, 17, 20, 17)
        line(4, 7, 5.5, 8.5); line(5.5, 8.5, 8, 5.5)
        p.drawRect(r(4.2, 11.2, 3, 3)); p.drawRect(r(4.2, 16.2, 3, 3))
    elif name == "activity":
        path = QPainterPath(QPointF(3 * x, 12 * x))
        path.lineTo(8 * x, 12 * x); path.lineTo(10 * x, 6 * x); path.lineTo(14 * x, 18 * x); path.lineTo(16 * x, 12 * x); path.lineTo(21 * x, 12 * x)
        p.drawPath(path)
    elif name == "settings":
        p.drawEllipse(r(8, 8, 8, 8))
        for a, b, c, d in ((12, 3, 12, 6), (12, 18, 12, 21), (3, 12, 6, 12), (18, 12, 21, 12), (5.7, 5.7, 7.8, 7.8), (16.2, 16.2, 18.3, 18.3), (16.2, 7.8, 18.3, 5.7), (5.7, 18.3, 7.8, 16.2)):
            line(a, b, c, d)
    elif name == "play":
        p.drawPolygon([QPointF(8*x, 5*x), QPointF(19*x, 12*x), QPointF(8*x, 19*x)])
    elif name == "terminal":
        p.drawRoundedRect(r(4, 5, 16, 14), 2 * x, 2 * x)
        line(7, 10, 10, 12); line(10, 12, 7, 14); line(12, 15, 17, 15)
    elif name == "layout-dashboard":
        p.drawRect(r(4, 5, 7, 6)); p.drawRect(r(13, 5, 7, 6)); p.drawRect(r(4, 13, 7, 6)); p.drawRect(r(13, 13, 7, 6))
    elif name == "plug":
        p.drawRoundedRect(r(8, 9, 8, 8), 2 * x, 2 * x)
        line(9, 5, 9, 9); line(15, 5, 15, 9); line(12, 17, 12, 21)
    elif name == "refresh":
        p.drawArc(r(5, 5, 14, 14), 30 * 16, 260 * 16); line(18, 6, 19, 11); line(18, 6, 13, 6)
    elif name == "folder":
        p.drawRoundedRect(r(3.5, 7, 17, 11), 2 * x, 2 * x); line(4, 9, 10, 9); line(10, 9, 12, 7)
    elif name == "send":
        p.drawPolygon([QPointF(4*x, 5*x), QPointF(20*x, 12*x), QPointF(4*x, 19*x), QPointF(8*x, 12*x)])
    elif name == "square":
        p.drawRoundedRect(r(7, 7, 10, 10), 2 * x, 2 * x)
    else:
        p.drawEllipse(r(6, 6, 12, 12))
