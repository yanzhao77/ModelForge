"""Plugin Manager - discovers, loads, and manages plugins."""
import importlib
import pkgutil
from typing import Dict, List, Type, Optional

from core.plugin_base import Plugin, ModelPlugin, ToolPlugin, RuntimePlugin


class PluginManager:
    """Central plugin registry and lifecycle manager."""

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> bool:
        """Register a plugin instance."""
        if plugin.name in self._plugins:
            return False
        self._plugins[plugin.name] = plugin
        return True

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name."""
        if name not in self._plugins:
            return False
        del self._plugins[name]
        return True

    def get(self, name: str) -> Optional[Plugin]:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list_all(self) -> List[Dict]:
        """List all registered plugins with their info."""
        return [p.get_info() for p in self._plugins.values()]

    def list_by_type(self, plugin_type: str) -> List[Dict]:
        """List plugins filtered by type."""
        return [
            p.get_info()
            for p in self._plugins.values()
            if p.plugin_type == plugin_type
        ]

    def install_all(self) -> Dict[str, bool]:
        """Install all registered plugins."""
        results = {}
        for name, plugin in self._plugins.items():
            try:
                results[name] = plugin.install()
            except Exception as e:
                results[name] = False
        return results

    def execute(self, name: str, **kwargs) -> Dict:
        """Execute a plugin by name."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return {"error": f"Plugin {chr(39)}{name}{chr(39)} not found"}
        try:
            result = plugin.execute(**kwargs)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def count(self) -> int:
        """Return number of registered plugins."""
        return len(self._plugins)
