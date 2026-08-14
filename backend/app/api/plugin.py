"""Plugin API routes."""
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/plugins", tags=["plugins"])


_plugin_manager = None


def set_plugin_manager(pm):
    global _plugin_manager
    _plugin_manager = pm


@router.get("")
async def list_plugins(type: Optional[str] = None):
    """List all plugins, optionally filtered by type."""
    if _plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not initialized")
    if type:
        return _plugin_manager.list_by_type(type)
    return _plugin_manager.list_all()


@router.post("/{name}/install")
async def install_plugin(name: str):
    """Install a specific plugin."""
    if _plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not initialized")
    plugin = _plugin_manager.get(name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    try:
        success = plugin.install()
        return {"name": name, "installed": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/install-all")
async def install_all_plugins():
    """Install all registered plugins."""
    if _plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not initialized")
    return _plugin_manager.install_all()


# ---- 3.x plugin lifecycle (additive; uses the runtime PluginManager) ----

def _runtime_pm():
    from services.agent_runtime_service import get_agent_runtime
    rt = get_agent_runtime()
    if rt is None:
        raise HTTPException(status_code=503, detail="Agent runtime not initialized")
    return rt.get_plugin_manager()


@router.get("/discover")
async def discover_plugins(directory: Optional[str] = None):
    """Discover plugin manifests on the filesystem (audit §16.9)."""
    return {"plugins": _runtime_pm().discover(directory)}


@router.get("/capabilities")
async def capabilities(scope: Optional[str] = None):
    """Capability index of loaded tools/skills/agent extensions (3.x-P6)."""
    from services.agent_runtime_service import get_agent_runtime
    rt = get_agent_runtime()
    if rt is None:
        raise HTTPException(status_code=503, detail="Agent runtime not initialized")
    return rt.discover_capabilities(scope_id=scope)


@router.post("/load")
async def load_plugin(req: dict):
    """Load a plugin from a manifest dict or a manifest path (audit §16.5)."""
    from runtime.plugins.manifest import PluginManifest
    pm = _runtime_pm()
    try:
        if (req or {}).get("manifest_path"):
            manifest = PluginManifest.from_file((req or {})["manifest_path"])
        else:
            manifest = PluginManifest.from_dict((req or {}).get("manifest") or {})
        state = pm.load(manifest)
        return {"name": manifest.name, "status": state["status"], "tools": sorted(state["scope"].tools().keys())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{name}/start")
async def start_plugin(name: str):
    if not _runtime_pm().start(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.post("/{name}/stop")
async def stop_plugin(name: str):
    if not _runtime_pm().stop(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.post("/{name}/mount")
async def mount_plugin(name: str):
    if not _runtime_pm().mount(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.post("/{name}/unmount")
async def unmount_plugin(name: str):
    if not _runtime_pm().unmount(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.delete("/{name}")
async def unload_plugin(name: str):
    if not _runtime_pm().unload(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}