"""Package export/import for models, agents, tools and workflows (V1.7).

A "package" is a self-describing JSON document: a manifest (id/kind/version/
license/dependencies/permissions) plus the payload needed to recreate the
entity on another ModelForge install.

Honesty rules:

* model packages carry *metadata* and runtime requirements, never weights and
  never an absolute path — the importer is told which artifact to download;
* tool packages carry the manifest + schema; the implementation stays in files
  (``entry``), so importing a tool records the requirement instead of executing
  arbitrary code;
* every package records the version it declares and a dependency list that is
  validated at import time.
"""

from __future__ import annotations

import datetime
import json
import uuid

from models.records import (
    AgentRecord,
    AgentTeam,
    AgentTeamMember,
    KnowledgeCollection,
    KnowledgeCollectionDocument,
    PlatformPackage,
    Workflow,
)

SUPPORTED_KINDS = ("model", "agent", "team", "workflow", "tool", "knowledge")
PACKAGE_SCHEMA_VERSION = 1


class PackageError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


class PackageService:
    """Export/import/browse ModelForge packages for one user."""

    def __init__(self, db):
        self.db = db

    # -- listing ------------------------------------------------------------

    def list(self, user_id: int, *, kind: str | None = None) -> list[dict]:
        query = self.db.query(PlatformPackage).filter(
            (PlatformPackage.user_id == user_id) | (PlatformPackage.user_id.is_(None))
        )
        if kind:
            query = query.filter(PlatformPackage.kind == kind)
        rows = query.order_by(PlatformPackage.created_at.desc()).all()
        return [row.to_dict() for row in rows]

    def get(self, user_id: int, package_id: str, version: str | None = None) -> dict:
        query = self.db.query(PlatformPackage).filter(PlatformPackage.package_id == package_id)
        if version:
            query = query.filter(PlatformPackage.version == version)
        query = query.filter(
            (PlatformPackage.user_id == user_id) | (PlatformPackage.user_id.is_(None))
        )
        row = query.order_by(PlatformPackage.created_at.desc()).first()
        if row is None:
            raise PackageError(
                "PACKAGE_NOT_FOUND", "Package not found.", {"package_id": package_id}, http_status=404
            )
        return row.to_dict(include_payload=True)

    def versions(self, user_id: int, package_id: str) -> list[str]:
        rows = (
            self.db.query(PlatformPackage.version)
            .filter(PlatformPackage.package_id == package_id)
            .filter((PlatformPackage.user_id == user_id) | (PlatformPackage.user_id.is_(None)))
            .all()
        )
        return sorted({version for (version,) in rows})

    def delete(self, user_id: int, package_id: str, version: str | None = None) -> int:
        query = self.db.query(PlatformPackage).filter(
            PlatformPackage.package_id == package_id, PlatformPackage.user_id == user_id
        )
        if version:
            query = query.filter(PlatformPackage.version == version)
        removed = query.delete(synchronize_session=False)
        self.db.commit()
        return int(removed or 0)

    # -- export -------------------------------------------------------------

    def export(
        self,
        user_id: int,
        *,
        kind: str,
        ref: str,
        version: str | None = None,
        license_name: str | None = None,
    ) -> dict:
        kind = (kind or "").strip().lower()
        if kind not in SUPPORTED_KINDS:
            raise PackageError(
                "PACKAGE_KIND_UNSUPPORTED",
                "Package kind must be one of " + ", ".join(SUPPORTED_KINDS) + ".",
                {"kind": kind},
            )
        builder = getattr(self, f"_export_{kind}")
        manifest, payload = builder(user_id, ref, version=version, license_name=license_name)
        document = {"schema_version": PACKAGE_SCHEMA_VERSION, "manifest": manifest, "payload": payload}
        self.db.add(
            PlatformPackage(
                id=uuid.uuid4().hex[:32],
                user_id=user_id,
                package_id=manifest["package_id"],
                kind=kind,
                version=manifest["version"],
                name=manifest["name"],
                description=manifest.get("description"),
                license=manifest.get("license"),
                manifest_json=json.dumps(manifest, ensure_ascii=False),
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
        )
        self.db.commit()
        return document

    def _manifest(
        self,
        *,
        kind: str,
        package_id: str,
        name: str,
        version: str | None,
        description: str | None,
        license_name: str | None,
        requires: list[dict],
        extra: dict,
    ) -> dict:
        return {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "package_id": f"{kind}:{package_id}",
            "kind": kind,
            "name": name,
            "version": version or "1.0.0",
            "description": description,
            "license": license_name or "unspecified",
            "requires": requires,
            "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
            **extra,
        }

    def _export_workflow(self, user_id: int, ref: str, *, version, license_name):
        from services.workflow_service import WorkflowService, WorkflowServiceError

        try:
            row = WorkflowService(self.db).require(user_id, ref)
        except WorkflowServiceError as exc:
            raise PackageError(exc.code, exc.message, exc.details, http_status=exc.http_status) from exc
        definition = row.definition()
        requires: list[dict] = []
        for node in definition.get("nodes") or []:
            config = node.get("config") or {}
            if node.get("type") == "agent" and config.get("agent_id"):
                requires.append({"kind": "agent", "ref": config["agent_id"]})
            if node.get("type") == "llm" and config.get("model_id"):
                requires.append({"kind": "model", "ref": str(config["model_id"])})
            if node.get("type") == "tool" and config.get("tool"):
                requires.append({"kind": "tool", "ref": config["tool"]})
        manifest = self._manifest(
            kind="workflow",
            package_id=row.id,
            name=row.name,
            version=version or str(row.version),
            description=row.description,
            license_name=license_name,
            requires=_dedupe(requires),
            extra={"node_types": sorted({node.get("type") for node in definition.get("nodes") or []})},
        )
        return manifest, {"definition": definition}

    def _export_agent(self, user_id: int, ref: str, *, version, license_name):
        row = (
            self.db.query(AgentRecord)
            .filter(AgentRecord.name == ref, AgentRecord.user_id == user_id)
            .first()
        )
        if row is None:
            raise PackageError("AGENT_NOT_FOUND", "Agent not found.", {"agent_id": ref}, http_status=404)
        payload = row.to_dict()
        requires: list[dict] = []
        if row.model_id is not None:
            requires.append({"kind": "model", "ref": str(row.model_id)})
        for tool in payload.get("tools") or []:
            requires.append({"kind": "tool", "ref": tool})
        for collection_id in (payload.get("knowledge_config") or {}).get("collection_ids") or []:
            requires.append({"kind": "knowledge", "ref": str(collection_id)})
        manifest = self._manifest(
            kind="agent",
            package_id=row.name,
            name=row.name,
            version=version,
            description=row.description,
            license_name=license_name,
            requires=_dedupe(requires),
            extra={"model_id": row.model_id, "tools": payload.get("tools") or []},
        )
        return manifest, {
            "definition": {
                "name": row.name,
                "description": row.description,
                "model": row.model,
                "model_id": row.model_id,
                "system_prompt": row.system_prompt,
                "tools": payload.get("tools") or [],
                "memory_config": payload.get("memory") or {},
                "knowledge_config": payload.get("knowledge_config") or {},
                "policy": payload.get("policy") or {},
                "runtime_config": payload.get("runtime_config") or {},
            }
        }

    def _export_team(self, user_id: int, ref: str, *, version, license_name):
        team = self.db.query(AgentTeam).filter(AgentTeam.id == ref, AgentTeam.user_id == user_id).first()
        if team is None:
            team = self.db.query(AgentTeam).filter(AgentTeam.name == ref, AgentTeam.user_id == user_id).first()
        if team is None:
            raise PackageError("AGENT_TEAM_NOT_FOUND", "Agent team not found.", {"team_id": ref}, http_status=404)
        members = (
            self.db.query(AgentTeamMember)
            .filter(AgentTeamMember.team_id == team.id, AgentTeamMember.user_id == user_id)
            .order_by(AgentTeamMember.created_at.asc())
            .all()
        )
        requires = _dedupe([{"kind": "agent", "ref": team.manager_agent_id}] + [{"kind": "agent", "ref": member.agent_id} for member in members])
        manifest = self._manifest(
            kind="team",
            package_id=team.id,
            name=team.name,
            version=version,
            description=team.description,
            license_name=license_name,
            requires=requires,
            extra={"strategy": team.strategy, "member_count": len(members)},
        )
        return manifest, {
            "definition": {
                "name": team.name,
                "description": team.description,
                "manager_agent_id": team.manager_agent_id,
                "strategy": team.strategy,
                "max_concurrency": team.max_concurrency,
                "timeout": team.timeout,
                "retry_policy": team.to_dict().get("retry_policy") or {},
                "shared_memory_id": team.shared_memory_id,
                "permission_policy_id": team.permission_policy_id,
                "members": [member.to_dict() for member in members if member.role != "MANAGER"],
            }
        }

    def _export_knowledge(self, user_id: int, ref: str, *, version, license_name):
        collection = self.db.query(KnowledgeCollection).filter(KnowledgeCollection.id == ref, KnowledgeCollection.user_id == user_id).first()
        if collection is None:
            collection = self.db.query(KnowledgeCollection).filter(KnowledgeCollection.name == ref, KnowledgeCollection.user_id == user_id).first()
        if collection is None:
            raise PackageError("KNOWLEDGE_COLLECTION_NOT_FOUND", "Knowledge collection not found.", {"collection_id": ref}, http_status=404)
        links = self.db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == collection.id).all()
        manifest = self._manifest(
            kind="knowledge",
            package_id=collection.id,
            name=collection.name,
            version=version,
            description=collection.description,
            license_name=license_name,
            requires=[],
            extra={"document_count": len(links)},
        )
        return manifest, {
            "collection": {
                "name": collection.name,
                "description": collection.description,
                "tags": collection.to_dict().get("tags", []) if hasattr(collection, "to_dict") else [],
                "document_ids": [link.document_id for link in links],
                "import": "metadata-only",
            }
        }

    def _export_model(self, user_id: int, ref: str, *, version, license_name):
        from services.model_registry import ModelRegistry, ModelRegistryError

        registry = ModelRegistry(self.db)
        try:
            record = registry.require(int(ref), user_id)
        except (ModelRegistryError, TypeError, ValueError) as exc:
            raise PackageError(
                "MODEL_NOT_FOUND", "Model not found.", {"model_id": ref}, http_status=404
            ) from exc
        requires = [
            {"kind": "runtime", "ref": runtime_id}
            for runtime_id in record.supported_runtime_list()
        ]
        manifest = self._manifest(
            kind="model",
            package_id=str(record.id),
            name=record.display_name or record.name,
            version=version,
            description=f"{record.format or 'unknown'} model",
            license_name=license_name,
            requires=requires,
            extra={
                "capabilities": registry.capabilities(record),
                "format": record.format,
                "quant": record.quant,
                "size_bytes": record.size_bytes,
                "metadata": record.metadata_dict(),
            },
        )
        # Weights never travel inside a package, and neither does the host path.
        return manifest, {
            "artifact": {
                "format": record.format,
                "size_bytes": record.size_bytes,
                "import": "download-required",
            }
        }

    def _export_tool(self, user_id: int, ref: str, *, version, license_name):
        del user_id
        from runtime.tools import ToolRegistry
        from runtime.tools.builtin import register_builtin_tools

        registry = register_builtin_tools(ToolRegistry())
        tool = registry.get(ref)
        if tool is None:
            raise PackageError("TOOL_NOT_FOUND", "Tool not found.", {"tool": ref}, http_status=404)
        manifest = self._manifest(
            kind="tool",
            package_id=tool.name,
            name=tool.name,
            version=version or getattr(tool, "version", "1.0.0"),
            description=tool.description,
            license_name=license_name,
            requires=[],
            extra={"permissions": list(getattr(tool, "permissions", []) or [])},
        )
        return manifest, {"schema": tool.schema(), "entry": getattr(tool, "source", "builtin")}

    # -- import -------------------------------------------------------------

    def import_document(self, user_id: int, document: dict, *, conflict: str = "rename") -> dict:
        if not isinstance(document, dict):
            raise PackageError("PACKAGE_INVALID", "Package must be a JSON object.")
        manifest = document.get("manifest")
        payload = document.get("payload")
        if not isinstance(manifest, dict) or not isinstance(payload, dict):
            raise PackageError("PACKAGE_INVALID", "Package needs manifest and payload objects.")
        kind = str(manifest.get("kind") or "").lower()
        if kind not in SUPPORTED_KINDS:
            raise PackageError(
                "PACKAGE_KIND_UNSUPPORTED", "Unsupported package kind.", {"kind": kind}
            )
        missing = self._missing_dependencies(user_id, manifest.get("requires") or [])
        result = getattr(self, f"_import_{kind}")(user_id, manifest, payload, conflict=conflict)
        row = PlatformPackage(
            id=uuid.uuid4().hex[:32],
            user_id=user_id,
            package_id=str(manifest.get("package_id") or manifest.get("name") or kind),
            kind=kind,
            version=str(manifest.get("version") or "1.0.0"),
            name=str(manifest.get("name") or kind),
            description=manifest.get("description"),
            license=manifest.get("license"),
            manifest_json=json.dumps(manifest, ensure_ascii=False),
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        self.db.add(row)
        self.db.commit()
        return {
            "package_id": row.package_id,
            "kind": kind,
            "version": row.version,
            "imported": result,
            "missing_dependencies": missing,
        }

    def _missing_dependencies(self, user_id: int, requires: list) -> list[dict]:
        """Report dependencies this install cannot satisfy yet."""
        from services.model_registry import ModelRegistry
        from services.runtimes.adapters import get_adapter

        registry = ModelRegistry(self.db)
        missing: list[dict] = []
        for requirement in requires:
            if not isinstance(requirement, dict):
                continue
            kind = str(requirement.get("kind") or "")
            ref = str(requirement.get("ref") or "")
            if kind == "model":
                resolved = registry.get(int(ref), user_id) if ref.isdigit() else None
                if resolved is None:
                    missing.append({"kind": "model", "ref": ref, "reason": "MODEL_NOT_REGISTERED"})
            elif kind == "agent":
                exists = (
                    self.db.query(AgentRecord.id)
                    .filter(AgentRecord.name == ref, AgentRecord.user_id == user_id)
                    .first()
                )
                if exists is None:
                    missing.append({"kind": "agent", "ref": ref, "reason": "AGENT_NOT_FOUND"})
            elif kind == "workflow":
                exists = (
                    self.db.query(Workflow.id)
                    .filter(Workflow.id == ref, Workflow.user_id == user_id)
                    .first()
                )
                if exists is None:
                    missing.append({"kind": "workflow", "ref": ref, "reason": "WORKFLOW_NOT_FOUND"})
            elif kind == "knowledge":
                exists = (
                    self.db.query(KnowledgeCollection.id)
                    .filter(KnowledgeCollection.id == ref, KnowledgeCollection.user_id == user_id)
                    .first()
                )
                if exists is None:
                    missing.append({"kind": "knowledge", "ref": ref, "reason": "KNOWLEDGE_NOT_FOUND"})
            elif kind == "runtime" and get_adapter(ref) is None:
                missing.append({"kind": "runtime", "ref": ref, "reason": "RUNTIME_UNAVAILABLE"})
        return missing

    def _import_workflow(self, user_id: int, manifest: dict, payload: dict, *, conflict: str) -> dict:
        from services.workflow_service import WorkflowService, WorkflowServiceError

        definition = payload.get("definition")
        if not isinstance(definition, dict):
            raise PackageError("PACKAGE_INVALID", "Workflow package needs payload.definition.")
        name = _unique_name(str(manifest.get("name") or "imported-workflow"), conflict)
        try:
            created = WorkflowService(self.db).create(
                user_id, {"name": name, "definition": definition}
            )
        except WorkflowServiceError as exc:
            raise PackageError(exc.code, exc.message, exc.details, http_status=exc.http_status) from exc
        return {"workflow_id": created["workflow_id"], "name": created["name"]}

    def _import_agent(self, user_id: int, manifest: dict, payload: dict, *, conflict: str) -> dict:
        from services.agent_runtime_service import get_agent_runtime
        from services.agent_service import AgentService, AgentServiceError

        definition = dict(payload.get("definition") or {})
        definition["name"] = _unique_name(
            str(definition.get("name") or manifest.get("name") or "imported-agent"), conflict
        )
        # A package may come from another machine where the model_id differs; the
        # name is kept so the agent can be re-bound instead of pointing at a
        # record that does not exist here.
        if not _model_available(self.db, user_id, definition.get("model_id")):
            definition.pop("model_id", None)
        try:
            agent = AgentService(self.db, runtime=get_agent_runtime()).create(user_id, definition)
        except AgentServiceError as exc:
            raise PackageError(exc.code, exc.message, exc.details, http_status=exc.http_status) from exc
        return {"agent_id": agent["name"], "model_id": agent.get("model_id")}

    def _import_team(self, user_id: int, manifest: dict, payload: dict, *, conflict: str) -> dict:
        from services.agent_team_service import AgentTeamError, AgentTeamService

        definition = dict(payload.get("definition") or {})
        definition["name"] = _unique_name(str(definition.get("name") or manifest.get("name") or "imported-team"), conflict)
        try:
            team = AgentTeamService(self.db).create_team(user_id, definition)
        except AgentTeamError as exc:
            raise PackageError(exc.code, exc.message, exc.details, http_status=exc.http_status) from exc
        return {"team_id": team["team_id"], "name": team["name"]}

    def _import_knowledge(self, user_id: int, manifest: dict, payload: dict, *, conflict: str) -> dict:
        collection = dict(payload.get("collection") or {})
        name = _unique_name(str(collection.get("name") or manifest.get("name") or "imported-knowledge"), conflict)
        row = KnowledgeCollection(
            id=uuid.uuid4().hex,
            user_id=user_id,
            name=name,
            description=collection.get("description") or manifest.get("description"),
            tags_json=json.dumps(collection.get("tags") or [], ensure_ascii=False),
        )
        self.db.add(row)
        self.db.flush()
        return {"collection_id": row.id, "name": row.name, "document_import": collection.get("import") or "metadata-only"}

    def _import_model(self, user_id: int, manifest: dict, payload: dict, *, conflict: str) -> dict:
        del user_id, conflict
        return {
            "model_id": None,
            "action_required": "download",
            "artifact": payload.get("artifact") or {},
            "capabilities": manifest.get("capabilities") or [],
            "note": "模型权重不随包传输，请按 format/size 重新下载后自动注册。",
        }

    def _import_tool(self, user_id: int, manifest: dict, payload: dict, *, conflict: str) -> dict:
        del user_id, conflict
        return {
            "tool": manifest.get("name"),
            "permissions": manifest.get("permissions") or [],
            "entry": payload.get("entry"),
            "action_required": "install-plugin",
            "note": "工具实现保存在文件中，导入只登记权限与 schema，不会执行代码。",
        }


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (item.get("kind"), item.get("ref"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _unique_name(name: str, conflict: str) -> str:
    return name if conflict == "overwrite" else f"{name}-imported"


def _model_available(db, user_id: int, model_id) -> bool:
    if model_id is None:
        return False
    from services.model_registry import ModelRegistry

    try:
        return ModelRegistry(db).get(int(model_id), user_id) is not None
    except (TypeError, ValueError):
        return False


__all__ = ["PACKAGE_SCHEMA_VERSION", "SUPPORTED_KINDS", "PackageError", "PackageService"]
