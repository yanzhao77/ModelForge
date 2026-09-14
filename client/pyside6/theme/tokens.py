"""Shared semantic tokens for the restrained macOS-style ModelForge UI."""
from __future__ import annotations

FONT_UI = "Helvetica Neue, PingFang SC, Hiragino Sans, Segoe UI, Microsoft YaHei, Yu Gothic, Noto Sans, Arial, sans-serif"
FONT_MONO = "Menlo, Monaco, Cascadia Mono, JetBrains Mono, Noto Sans Mono CJK SC, monospace"
SIDEBAR_WIDTH = 216
TOPBAR_HEIGHT = 52
MIN_WINDOW_WIDTH = 1024
MIN_WINDOW_HEIGHT = 680
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 8

LIGHT = {
    "bg": "#F5F6F8", "sidebar": "#ECEEF1", "surface": "#FFFFFF", "surface_subtle": "#F2F3F5",
    "hover": "#E9EDF2", "border": "#DDE1E7", "border_strong": "#7B8491",
    "text": "#20242B", "muted": "#596270", "dim": "#929AA6", "accent": "#0066CC",
    "accent_fg": "#FFFFFF", "success": "#177245", "warning": "#946200", "danger": "#B42332",
    "info": "#0066CC", "selection": "#E5F0FF", "focus": "#0066CC",
}

DARK = {
    "bg": "#17181A", "sidebar": "#202124", "surface": "#242528", "surface_subtle": "#2B2D31",
    "hover": "#33363C", "border": "#3D4149", "border_strong": "#8B949F",
    "text": "#F4F5F7", "muted": "#B3BAC5", "dim": "#767E89", "accent": "#0A66CE",
    "accent_fg": "#FFFFFF", "success": "#72D7A0", "warning": "#EDC269", "danger": "#FF98A0",
    "info": "#7CB7FF", "selection": "#253A54", "focus": "#87BCFF",
}
