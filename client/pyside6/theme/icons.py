ICONS = {
    "overview": "◈",
    "chat": "◇",
    "models": "▣",
    "datasets": "▤",
    "training": "▥",
    "knowledge": "⌘",
    "agents": "◉",
    "workbench": "◫",
    "automation": "◷",
    "control": "⊞",
    "extensions": "▧",
    "developer": "⌁",
    "tasks": "◎",
    "runtime": "◉",
    "activity": "⋮",
    "settings": "⊚",
    "online": "●",
}


def glyph(name: str, fallback: str = "·") -> str:
    return ICONS.get(name, fallback)
