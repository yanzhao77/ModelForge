from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict, List, Optional

from ..logging import get_logger, log_run
from .manifest import PluginManifest


PLUGIN_LIFECYCLE_EVENTS = (
    "plugin.discovered", "plugin.loaded", "plugin.started", "plugin.stopped",
    "plugin.mounted", "plugin.unmounted", "plugin.failed", "plugin.unloaded",
)


class PluginManager:
    """Loads, starts and mounts plugins (audit §16.5/§16.6/§16.10).

    Lifecycle events are published on the SINGLE EventBus (spec 7 / audit §10.3);
    no second event system. Each plugin gets a PluginScope + PluginContext.
    """

    def __init__(
        self,
        runtime: Any,
        plugins_dir: Optional[str] = None,
        event_bus: Any = None,
        logger: Any = None,
    ):
        self._runtime = runtime
        self._plugins_dir = plugins_dir
        self._event_bus = event_bus or getattr(runtime, "event_bus", None)
        self._logger = logger or get_logger()
        self._plugins: Dict[str, Dict[str, Any]] = {}

    # ---- discovery (audit §16.9) ----
    def discover(self, directory: Optional[str] = None) -> List[Dict[str, Any]]:
        """Scan `*/plugin.yaml|plugin.json` under a directory."""
        directory = directory or self._plugins_dir
        found = []
        if not directory or not os.path.isdir(directory):
            return found
        for entry in sorted(os.listdir(directory)):
            pdir = os.path.join(directory, entry)
            if not os.path.isdir(pdir):
                continue
            for manifest_file in ("plugin.yaml", "plugin.yml", "plugin.json"):
                mpath = os.path.join(pdir, manifest_file)
                if os.path.exists(mpath):
                    try:
                        m = PluginManifest.from_file(mpath)
                        problems = m.validate()
                        found.append({**m.to_dict(), "manifest_path": mpath, "problems": problems})
                    except Exception as e:
                        found.append({"name": entry, "version": "?", "problems": [f"manifest error: {e}"], "manifest_path": mpath})
                    break
        return found

    # ---- lifecycle ----
    def load(self, manifest: PluginManifest) -> Dict[str, Any]:
        """Resolve dependencies, create scope/context, import entry, mount tools."""
        if manifest.name in self._plugins:
            return self._plugins[manifest.name]
        problems = manifest.validate()
        if problems:
            raise ValueError(f"invalid plugin {manifest.name}: {problems}")
        for dep in manifest.dependencies:
            if dep not in self._plugins:
                raise ValueError(f"plugin {manifest.name} depends on missing plugin: {dep}")

        scope = self._runtime.create_scope(f"plugin:{manifest.name}", name=manifest.name)
        ctx = scope.context(manifest.name, config=manifest.config)
        state: Dict[str, Any] = {
            "manifest": manifest,
            "scope": scope,
            "context": ctx,
            "status": "loaded",
            "error": None,
        }
        self._plugins[manifest.name] = state
        self._emit("plugin.loaded", {"name": manifest.name, "version": manifest.version, "type": manifest.type})

        # import entry module (code stays on filesystem, audit §17)
        if manifest.entry:
            module = self._import_entry(manifest.entry)
            state["module"] = module
            try:
                if hasattr(module, "setup"):
                    result = module.setup(ctx)
                    if isinstance(result, list):
                        for tool in result:
                            ctx.register_tool(tool)
                if hasattr(module, "get_tools"):
                    for tool in module.get_tools(ctx) or []:
                        ctx.register_tool(tool)
                # agent plugins: behavior extension merged into the agent profile (3.x-P3)
                if manifest.type == "agent" and hasattr(module, "extend_agent"):
                    ext = module.extend_agent(ctx) or {}
                    if isinstance(ext, dict):
                        mounted_names = []
                        for tool in ext.get("tools") or []:
                            ctx.register_tool(tool)
                            mounted_names.append(getattr(tool, "name", ""))
                        ext["tool_names"] = mounted_names
                        state["extension"] = ext
            except Exception as e:
                state["status"] = "failed"
                state["error"] = str(e)
                self._emit("plugin.failed", {"name": manifest.name, "error": str(e)})
                raise
        # manifest-declared tools with entry-provided schemas are registered by
        # the entry itself; plain descriptors are informational here.
        return state

    def start(self, name: str) -> bool:
        state = self._plugins.get(name)
        if state is None or state["status"] == "failed":
            return False
        state["status"] = "started"
        self._emit("plugin.started", {"name": name})
        return True

    def stop(self, name: str) -> bool:
        state = self._plugins.get(name)
        if state is None:
            return False
        state["status"] = "loaded"
        self._emit("plugin.stopped", {"name": name})
        return True

    def mount(self, name: str) -> bool:
        """Confirm the plugin tools are active (they are mounted at load time)."""
        state = self._plugins.get(name)
        if state is None:
            return False
        self._emit("plugin.mounted", {"name": name, "tools": sorted(state["scope"].tools().keys())})
        return True

    def unmount(self, name: str) -> bool:
        state = self._plugins.get(name)
        if state is None:
            return False
        state["scope"].unmount()
        self._emit("plugin.unmounted", {"name": name})
        return True

    def unload(self, name: str) -> bool:
        state = self._plugins.pop(name, None)
        if state is None:
            return False
        state["scope"].unmount()
        self._emit("plugin.unloaded", {"name": name})
        return True

    def list(self) -> List[Dict[str, Any]]:
        return [{
            "name": name,
            "version": s["manifest"].version,
            "type": s["manifest"].type,
            "status": s["status"],
            "dependencies": list(s["manifest"].dependencies),
            "tools": sorted(s["scope"].tools().keys()),
            "error": s.get("error"),
        } for name, s in sorted(self._plugins.items())]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._plugins.get(name)

    def dependencies_of(self, name: str) -> List[str]:
        state = self._plugins.get(name)
        return list(state["manifest"].dependencies) if state else []

    # ---- internals ----
    def _import_entry(self, entry: str) -> Any:
        """Import the plugin entry module from a file path (no sys.path pollution)."""
        if not os.path.isabs(entry) and self._plugins_dir:
            candidate = os.path.join(self._plugins_dir, entry)
            if os.path.exists(candidate):
                entry = candidate
        spec = importlib.util.spec_from_file_location(f"mf_plugin_{abs(hash(entry))}", entry)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_bus is None:
            return
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._event_bus.publish("plugin:manager", event_type, payload=payload, correlation_id="plugin-manager"))
        except RuntimeError:
            pass