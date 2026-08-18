"""Plugin Manager - discovers, loads, and manages plugins."""

from core.plugin_base import Plugin


class PluginManager:
    """Central plugin registry and lifecycle manager."""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}

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

    def get(self, name: str) -> Plugin | None:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list_all(self) -> list[dict]:
        """List all registered plugins with their info."""
        return [p.get_info() for p in self._plugins.values()]

    def list_by_type(self, plugin_type: str) -> list[dict]:
        """List plugins filtered by type."""
        return [
            p.get_info()
            for p in self._plugins.values()
            if p.plugin_type == plugin_type
        ]

    def install_all(self) -> dict[str, bool]:
        """Install all registered plugins."""
        results = {}
        for name, plugin in self._plugins.items():
            try:
                results[name] = plugin.install()
            except Exception:
                results[name] = False
        return results

    def execute(self, name: str, **kwargs) -> dict:
        """Execute a plugin by name."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return {"error": f"Plugin '{name}' not found"}
        try:
            result = plugin.execute(**kwargs)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def count(self) -> int:
        """Return number of registered plugins."""
        return len(self._plugins)


_manager = None

def get_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager