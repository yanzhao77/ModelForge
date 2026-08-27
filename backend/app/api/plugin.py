"""Plugin API routes."""

from typing import Any

from core.action_risk import requires_confirmation
from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_runtime_admin
from fastapi import APIRouter, Depends, HTTPException
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import (
    AuditMetadataRejected,
    AuditPersistenceError,
    commit_control_plane_audit,
    record_control_plane_operation,
    validate_control_plane_audit_metadata,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/plugins", tags=["plugins"])


_plugin_manager = None


class PluginConfirmation(BaseModel):
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


class PluginLoadRequest(PluginConfirmation):
    manifest_path: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)


def _audit_operation(db: Session, user: User, action: str, name: str, payload: dict[str, Any], req: PluginConfirmation, correlation: str) -> dict:
    """Persist only an action summary, then return a correlatable response."""
    audit_action = f"plugin.{action}"
    metadata = {"confirmed": bool(req.confirm), "request_id_supplied": bool(req.request_id), "operation": action}
    try:
        validate_control_plane_audit_metadata(audit_action, metadata)
        record_control_plane_operation(db, user_id=user.id, action=audit_action, object_type="runtime_plugin", object_id=name, correlation_id=correlation, metadata=metadata)
        commit_control_plane_audit(db)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    except AuditPersistenceError as exc:
        raise problem(503, "PLUGIN_AUDIT_DURABILITY_UNKNOWN", "Plugin action was accepted, but audit durability is unknown.", correlation=correlation) from exc
    return operation_result(payload, correlation)


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
async def install_plugin(name: str, req: PluginConfirmation, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    """Install a specific plugin."""
    correlation = _confirmed(req, "plugin.install")
    if _plugin_manager is None:
        raise problem(503, "PLUGIN_MANAGER_UNAVAILABLE", "Plugin manager not initialized", correlation=correlation)
    plugin = _plugin_manager.get(name)
    if plugin is None:
        raise problem(404, "PLUGIN_NOT_FOUND", "Plugin not found")
    try:
        success = plugin.install()
        return _audit_operation(db, user, "install", name, {"name": name, "installed": bool(success)}, req, correlation)
    except Exception:
        raise problem(500, "PLUGIN_INSTALL_FAILED", "Plugin install failed")


@router.post("/install-all")
async def install_all_plugins(req: PluginConfirmation, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    """Install all registered plugins."""
    correlation = _confirmed(req, "plugin.install_all")
    if _plugin_manager is None:
        raise problem(503, "PLUGIN_MANAGER_UNAVAILABLE", "Plugin manager not initialized", correlation=correlation)
    result = _plugin_manager.install_all()
    return _audit_operation(db, user, "install_all", "all", {"ok": True, "result": result}, req, correlation)


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
async def load_plugin(req: PluginLoadRequest, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    """Load a plugin from a manifest dict or a manifest path (audit §16.5)."""
    correlation = _confirmed(req, "plugin.load")
    from runtime.plugins.manifest import PluginManifest
    pm = _runtime_pm()
    try:
        if req.manifest_path:
            manifest = PluginManifest.from_file(req.manifest_path)
        else:
            manifest = PluginManifest.from_dict(req.manifest or {})
        state = pm.load(manifest)
        return _audit_operation(db, user, "load", manifest.name, {"name": manifest.name, "status": state["status"], "tool_count": len(state["scope"].tools())}, req, correlation)
    except HTTPException:
        raise
    except Exception:
        raise problem(400, "PLUGIN_LOAD_FAILED", "Plugin load failed")


def _confirmed(req: PluginConfirmation, action: str) -> str:
    correlation = req.request_id or correlation_id()
    if requires_confirmation(action) and not req.confirm:
        raise problem(409, "PLUGIN_CONFIRM_REQUIRED", "Explicit confirm=true is required for plugin lifecycle changes", correlation=correlation)
    return correlation


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
async def start_plugin(name: str, req: PluginConfirmation, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    correlation = _confirmed(req, "plugin.start")
    if not _runtime_pm().start(name):
        raise problem(404, "PLUGIN_NOT_LOADED", "Plugin not loaded")
    return _audit_operation(db, user, "start", name, {"ok": True, "name": name}, req, correlation)


@router.post("/{name}/stop")
async def stop_plugin(name: str, req: PluginConfirmation, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    correlation = _confirmed(req, "plugin.stop")
    if not _runtime_pm().stop(name):
        raise problem(404, "PLUGIN_NOT_LOADED", "Plugin not loaded")
    return _audit_operation(db, user, "stop", name, {"ok": True, "name": name}, req, correlation)


@router.post("/{name}/mount")
async def mount_plugin(name: str, req: PluginConfirmation, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    correlation = _confirmed(req, "plugin.mount")
    if not _runtime_pm().mount(name):
        raise problem(404, "PLUGIN_NOT_LOADED", "Plugin not loaded")
    return _audit_operation(db, user, "mount", name, {"ok": True, "name": name}, req, correlation)


@router.post("/{name}/unmount")
async def unmount_plugin(name: str, req: PluginConfirmation, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    correlation = _confirmed(req, "plugin.unmount")
    if not _runtime_pm().unmount(name):
        raise problem(404, "PLUGIN_NOT_LOADED", "Plugin not loaded")
    return _audit_operation(db, user, "unmount", name, {"ok": True, "name": name}, req, correlation)


@router.delete("/{name}")
async def unload_plugin(name: str, req: PluginConfirmation, db: Session = Depends(get_db), user: User = Depends(get_runtime_admin)):
    correlation = _confirmed(req, "plugin.unload")
    impact = _runtime_pm().impact(name)
    if impact is not None and impact["unload_blocked"]:
        raise problem(409, "PLUGIN_UNLOAD_BLOCKED", "Plugin unload is blocked by a dependency")
    if not _runtime_pm().unload(name):
        raise problem(404, "PLUGIN_NOT_LOADED", "Plugin not loaded")
    return _audit_operation(db, user, "unload", name, {"ok": True, "name": name}, req, correlation)
