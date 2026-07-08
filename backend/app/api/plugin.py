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
        raise HTTPException(status_code=404, detail=f"Plugin {chr(39)}{name}{chr(39)} not found")
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