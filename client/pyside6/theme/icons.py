"""Minimal geometric symbol map for the ModelForge desktop UI."""
ICONS = {
    "overview": "◈", "chat": "◇", "models": "▣", "datasets": "▤",
    "training": "▥", "knowledge": "⌘", "agents": "◉", "tasks": "◎",
    "runtime": "▧", "activity": "⋮", "settings": "⊚", "online": "●",
    "workbench": "◫", "automation": "◔", "control": "⊞", "extensions": "⊕",
}


def glyph(name: str, fallback: str = "·") -> str:
    return ICONS.get(name, fallback)
