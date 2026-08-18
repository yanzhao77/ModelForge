from __future__ import annotations

from typing import Any


class CapabilityDiscovery:
    """Read-only capability index (audit §16.9 / §17).

    Aggregates tools (builtin / plugin / MCP) + skill contributions + agent
    extensions into one discoverable index, optionally filtered by scope.
    """

    def __init__(self, runtime: Any):
        self._runtime = runtime

    def discover(self, scope_id: str | None = None) -> dict[str, Any]:
        return {
            "tools": self._tools(scope_id),
            "skills": self._skills(scope_id),
            "agent_extensions": self._agent_extensions(scope_id),
        }

    def _tools(self, scope_id: str | None) -> list[dict[str, Any]]:
        registry = getattr(self._runtime, "tool_registry", None)
        if registry is None:
            return []
        out = []
        for tool in registry.list():
            meta = getattr(tool, "metadata", None) or {}
            tool_scope = meta.get("scope")
            if scope_id is not None and tool_scope != scope_id:
                continue
            entry: dict[str, Any] = {
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "source": getattr(tool, "source", "builtin"),
                "permissions": list(getattr(tool, "permissions", []) or []),
                "timeout": getattr(tool, "timeout", 60),
            }
            if tool_scope:
                entry["scope"] = tool_scope
            out.append(entry)
        return sorted(out, key=lambda x: x["name"])

    def _skills(self, scope_id: str | None) -> list[dict[str, Any]]:
        pm = getattr(self._runtime, "plugin_manager", None)
        if pm is None:
            return []
        out = []
        for state in list(getattr(pm, "_plugins", {}).values()):
            manifest = state.get("manifest")
            if manifest is None or manifest.type != "skill":
                continue
            contributions = state.get("contributions") or []
            out.append({
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "contribution_count": len(contributions),
                "sections": sorted({c.get("section", "system") for c in contributions}),
                "scope": f"plugin:{manifest.name}",
            })
        return sorted(out, key=lambda x: x["name"])

    def _agent_extensions(self, scope_id: str | None) -> list[dict[str, Any]]:
        pm = getattr(self._runtime, "plugin_manager", None)
        if pm is None:
            return []
        out = []
        for state in list(getattr(pm, "_plugins", {}).values()):
            manifest = state.get("manifest")
            ext = state.get("extension")
            if manifest is None or manifest.type != "agent" or not ext:
                continue
            out.append({
                "name": manifest.name,
                "version": manifest.version,
                "tools": list(ext.get("tool_names") or []),
                "policy": list((ext.get("policy") or {}).keys()),
                "knowledge_sources": list(ext.get("knowledge_sources") or []),
                "scope": f"plugin:{manifest.name}",
            })
        return sorted(out, key=lambda x: x["name"])