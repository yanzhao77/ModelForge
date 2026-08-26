"""Plugin API routes."""

from core.security import get_runtime_admin
from fastapi import APIRouter, Depends, HTTPException
from models.records import User

router = APIRouter(prefix="/plugins", tags=["plugins"])


_plugin_manager = None


def set_plugin_manager(pm):
    global _plugin_manager
    _plugin_manager = pm


@router.get("")
async def list_plugins(type: str | None = None):
    """List all plugins, optionally filtered by type."""
    if _plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not initialized")
    if type:
        return _plugin_manager.list_by_type(type)
    return _plugin_manager.list_all()


@router.post("/{name}/install")
async def install_plugin(name: str, req: dict | None = None, user: User = Depends(get_runtime_admin)):
    """Install a specific plugin."""
    if _plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not initialized")
    _confirmed(req)
    plugin = _plugin_manager.get(name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    try:
        success = plugin.install()
        return {"name": name, "installed": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/install-all")
async def install_all_plugins(req: dict | None = None, user: User = Depends(get_runtime_admin)):
    """Install all registered plugins."""
    if _plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not initialized")
    _confirmed(req)
    return _plugin_manager.install_all()


# ---- 3.x plugin lifecycle (additive; uses the runtime PluginManager) ----

def _runtime_pm():
    from services.agent_runtime_service import get_agent_runtime
    rt = get_agent_runtime()
    if rt is None:
        raise HTTPException(status_code=503, detail="Agent runtime not initialized")
    return rt.get_plugin_manager()


@router.get("/runtime")
async def runtime_plugins(user: User = Depends(get_runtime_admin)):
    """List already-loaded runtime plugins without discovery, loading, or startup."""
    return {"plugins": _runtime_pm().list()}


@router.get("/discover")
async def discover_plugins(directory: str | None = None, user: User = Depends(get_runtime_admin)):
    """Discover plugin manifests on the filesystem (audit §16.9)."""
    return {"plugins": _runtime_pm().discover(directory)}


@router.get("/capabilities")
async def capabilities(scope: str | None = None, user: User = Depends(get_runtime_admin)):
    """Capability index of loaded tools/skills/agent extensions (3.x-P6)."""
    from services.agent_runtime_service import get_agent_runtime
    rt = get_agent_runtime()
    if rt is None:
        raise HTTPException(status_code=503, detail="Agent runtime not initialized")
    return rt.discover_capabilities(scope_id=scope)


@router.post("/load")
async def load_plugin(req: dict, user: User = Depends(get_runtime_admin)):
    """Load a plugin from a manifest dict or a manifest path (audit §16.5)."""
    from runtime.plugins.manifest import PluginManifest
    pm = _runtime_pm()
    if (req or {}).get("confirm") is not True:
        raise HTTPException(status_code=409, detail="Explicit confirm=true is required to load plugin code")
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


def _confirmed(req: dict | None) -> None:
    if (req or {}).get("confirm") is not True:
        raise HTTPException(status_code=409, detail="Explicit confirm=true is required for plugin lifecycle changes")


@router.get("/{name}/impact")
async def plugin_impact(name: str, user: User = Depends(get_runtime_admin)):
    result = _runtime_pm().impact(name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return result


@router.post("/{name}/health")
async def plugin_health(name: str, user: User = Depends(get_runtime_admin)):
    result = _runtime_pm().health(name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return result


@router.post("/{name}/start")
async def start_plugin(name: str, req: dict | None = None, user: User = Depends(get_runtime_admin)):
    _confirmed(req)
    if not _runtime_pm().start(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.post("/{name}/stop")
async def stop_plugin(name: str, req: dict | None = None, user: User = Depends(get_runtime_admin)):
    _confirmed(req)
    if not _runtime_pm().stop(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.post("/{name}/mount")
async def mount_plugin(name: str, req: dict | None = None, user: User = Depends(get_runtime_admin)):
    _confirmed(req)
    if not _runtime_pm().mount(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.post("/{name}/unmount")
async def unmount_plugin(name: str, req: dict | None = None, user: User = Depends(get_runtime_admin)):
    _confirmed(req)
    if not _runtime_pm().unmount(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}


@router.delete("/{name}")
async def unload_plugin(name: str, req: dict | None = None, user: User = Depends(get_runtime_admin)):
    _confirmed(req)
    impact = _runtime_pm().impact(name)
    if impact is not None and impact["unload_blocked"]:
        raise HTTPException(status_code=409, detail=f"Plugin {name} is required by: {', '.join(impact['dependents'])}")
    if not _runtime_pm().unload(name):
        raise HTTPException(status_code=404, detail=f"Plugin {name} not loaded")
    return {"ok": True, "name": name}
