"""AgentDefinition service (V1.1): the `/api/v1/agents` surface.

An Agent is defined by ``model_id`` (a ModelRegistry reference) rather than a
model path or an arbitrary name, so the same asset powers Chat, Training, Agent
runs and the OpenAI-compatible API. This service owns create/read/update/delete
and keeps the Agent runtime (and the legacy 2.1 engine) in sync.
"""

from __future__ import annotations

import json
import uuid

from core.api_contracts import problem
from models.records import AgentDefinitionVersion, AgentRecord, KnowledgeCollection
from runtime.types import AgentConfig
from services.agent_model_provider import local_model_target
from services.model_readiness_service import ModelReadinessService
from services.model_registry import ModelRegistry, ModelRegistryError


class AgentServiceError(ValueError):
    """Stable agent-definition failure mapped onto the problem contract."""

    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status

    def to_problem(self, correlation: str | None = None):
        return problem(self.http_status, self.code, self.message, correlation=correlation, details=self.details or None)


class AgentService:
    """CRUD for AgentDefinitions bound to registry models."""

    def __init__(self, db, runtime=None, engine=None):
        self.db = db
        self.runtime = runtime
        self.engine = engine

    # -- reads --------------------------------------------------------------

    def get(self, agent_id: str, user_id: int) -> AgentRecord | None:
        return (
            self.db.query(AgentRecord)
            .filter(AgentRecord.name == agent_id, AgentRecord.user_id == user_id)
            .first()
        )

    def require(self, agent_id: str, user_id: int) -> AgentRecord:
        record = self.get(agent_id, user_id)
        if record is None:
            raise AgentServiceError("AGENT_NOT_FOUND", "Agent not found.", {"agent_id": agent_id}, http_status=404)
        return record

    def list(self, user_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = (
            self.db.query(AgentRecord)
            .filter(AgentRecord.user_id == user_id)
            .order_by(AgentRecord.created_at.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [self._payload(row) for row in rows]

    @staticmethod
    def _payload(row: AgentRecord) -> dict:
        payload = row.to_dict()
        payload["definition"] = {
            "agent_id": row.name,
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
            "status": row.status,
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }
        return payload

    # -- writes -------------------------------------------------------------

    def create(self, user_id: int, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise AgentServiceError("AGENT_NAME_REQUIRED", "Agent name is required.")
        if len(name) > 160:
            raise AgentServiceError("AGENT_NAME_TOO_LONG", "Agent name is too long.")
        existing = self.db.query(AgentRecord).filter(AgentRecord.name == name).first()
        if existing is not None and existing.user_id != user_id:
            raise AgentServiceError("AGENT_NAME_TAKEN", "Agent name is already owned by another account.", http_status=409)

        model, model_id, target, runtime_config = self._resolve_model(user_id, payload)
        knowledge_config = self._resolve_knowledge(user_id, payload.get("knowledge_config"))
        if runtime_config.get("runtime") and model_id is None:
            raise AgentServiceError("AGENT_RUNTIME_REQUIRES_MODEL_ID", "Selecting a runtime requires a registry model_id.")
        policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else None
        memory_config = payload.get("memory_config") if isinstance(payload.get("memory_config"), dict) else None
        tools = [str(item) for item in (payload.get("tools") or [])]
        description = payload.get("description")
        system_prompt = payload.get("system_prompt")
        version = self._next_version(user_id, name)

        if existing is None:
            row = AgentRecord(name=name)
            self.db.add(row)
        else:
            row = existing
        row.user_id = user_id
        row.model = model
        row.model_id = model_id
        row.tools = json.dumps(tools, ensure_ascii=False) if tools else None
        row.system_prompt = system_prompt
        row.description = description
        row.memory = json.dumps(memory_config, ensure_ascii=False) if memory_config else None
        row.policy = json.dumps(policy, ensure_ascii=False) if policy else None
        row.knowledge_config = json.dumps(knowledge_config, ensure_ascii=False) if knowledge_config else None
        row.runtime_config = json.dumps(runtime_config, ensure_ascii=False) if runtime_config else None
        row.status = str(payload.get("status") or "active")
        self.db.flush()
        self._snapshot(user_id, name, version, "Initial definition" if existing is None else "Definition updated")
        self.db.commit()
        self.db.refresh(row)
        self._register_with_runtime(row, target)
        return self._payload(row)

    def update(self, user_id: int, agent_id: str, payload: dict) -> dict:
        row = self.require(agent_id, user_id)
        merged = {
            "name": agent_id,
            "description": payload.get("description", row.description),
            "system_prompt": payload.get("system_prompt", row.system_prompt),
            "tools": payload.get("tools", json.loads(row.tools) if row.tools else []),
            "memory_config": payload.get("memory_config", json.loads(row.memory) if row.memory else {}),
            "knowledge_config": payload.get("knowledge_config", json.loads(row.knowledge_config) if row.knowledge_config else {}),
            "policy": payload.get("policy", json.loads(row.policy) if row.policy else {}),
            "model_id": payload.get("model_id", row.model_id),
            "model": payload.get("model", row.model),
            "model_target": payload.get("model_target"),
            "runtime_config": payload.get("runtime_config", json.loads(row.runtime_config) if row.runtime_config else {}),
            "status": payload.get("status", row.status),
        }
        return self._write(user_id, agent_id, merged, version_note="Definition updated")

    def _write(self, user_id: int, agent_id: str, payload: dict, *, version_note: str) -> dict:
        # Reuse create() so model/knowledge validation and runtime registration
        # stay in one place; it also records the new definition version.
        payload = {**payload, "name": agent_id}
        if not payload.get("model_target") and payload.get("model_id") is None and not payload.get("model"):
            raise AgentServiceError("AGENT_MODEL_REQUIRED", "Agent requires a model or model_id.")
        del version_note
        return self.create(user_id, payload)

    def delete(self, user_id: int, agent_id: str) -> bool:
        row = self.get(agent_id, user_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        if self.runtime is not None:
            self.runtime.delete_agent(agent_id, user_id=user_id)
        if self.engine is not None:
            try:
                self.engine.delete_agent(agent_id, user_id=user_id)
            except Exception:
                pass
        return True

    # -- helpers ------------------------------------------------------------

    def _resolve_model(self, user_id: int, payload: dict) -> tuple[str, int | None, dict | None, dict]:
        """Resolve the model reference into (name, model_id, target, runtime_config)."""
        runtime_config = dict(payload.get("runtime_config") or {})
        model_id = payload.get("model_id")
        if model_id is not None:
            registry = ModelRegistry(self.db)
            try:
                model_id = int(model_id)
            except (TypeError, ValueError) as exc:
                raise AgentServiceError("MODEL_NOT_FOUND", "model_id must be numeric.", http_status=400) from exc
            try:
                record = registry.require(model_id, user_id)
                registry.require_ready(record)
                registry.require_capability(record, "CHAT")
            except ModelRegistryError as exc:
                raise AgentServiceError(exc.code, exc.message, exc.details, http_status=exc.http_status) from exc
            name = record.display_name or record.name
            target = local_model_target(model_id, name, registry.capabilities(record))
            runtime_config.setdefault("model_target", target)
            return name, model_id, target, runtime_config

        target_payload = payload.get("model_target")
        if isinstance(target_payload, dict) and target_payload.get("kind") == "remote":
            target = ModelReadinessService(self.db).target_for(
                user_id,
                kind="remote",
                model_ref=str(target_payload.get("model_ref") or ""),
                provider_id=target_payload.get("provider_id"),
            )
            if target is None or target.get("model_name") != target_payload.get("model_name"):
                raise AgentServiceError(
                    "MODEL_TARGET_NOT_READY",
                    "Selected Agent model target is not ready for this user.",
                    http_status=422,
                )
            runtime_config.setdefault("model_target", target)
            return target["model_name"], None, target, runtime_config

        model = str(payload.get("model") or "").strip()
        if not model:
            raise AgentServiceError("AGENT_MODEL_REQUIRED", "Agent requires a model or model_id.")
        # A bare name that matches a registry model is promoted to its model_id,
        # so the Agent goes through the runtime manager like every other caller
        # instead of falling back to a legacy backend.
        from services.model_resolver import ModelResolver

        record = ModelResolver(self.db).resolve(model, user_id)
        if record is not None:
            registry = ModelRegistry(self.db)
            try:
                registry.require_ready(record)
                registry.require_capability(record, "CHAT")
            except ModelRegistryError as exc:
                raise AgentServiceError(exc.code, exc.message, exc.details, http_status=exc.http_status) from exc
            name = record.display_name or record.name
            target = local_model_target(record.id, name, registry.capabilities(record))
            runtime_config.setdefault("model_target", target)
            return name, record.id, target, runtime_config
        return model, None, None, runtime_config

    def _resolve_knowledge(self, user_id: int, value) -> dict:
        knowledge_config = dict(value or {}) if isinstance(value, dict) else {}
        collection_ids = [str(item) for item in (knowledge_config.get("collection_ids") or [])]
        if not collection_ids:
            return knowledge_config
        owned = (
            self.db.query(KnowledgeCollection.id)
            .filter(KnowledgeCollection.user_id == user_id, KnowledgeCollection.id.in_(collection_ids))
            .all()
        )
        owned_ids = {row[0] for row in owned}
        missing = [item for item in collection_ids if item not in owned_ids]
        if missing:
            raise AgentServiceError(
                "KNOWLEDGE_COLLECTION_UNAVAILABLE",
                "Selected knowledge collection is not available to this user.",
                {"collection_ids": missing},
                http_status=422,
            )
        knowledge_config["collection_ids"] = list(dict.fromkeys(collection_ids))
        return knowledge_config

    def _next_version(self, user_id: int, agent_name: str) -> int:
        return (
            self.db.query(AgentDefinitionVersion)
            .filter(AgentDefinitionVersion.user_id == user_id, AgentDefinitionVersion.agent_name == agent_name)
            .count()
            + 1
        )

    def _snapshot(self, user_id: int, agent_name: str, version: int, note: str) -> None:
        self.db.add(
            AgentDefinitionVersion(
                id=uuid.uuid4().hex,
                user_id=user_id,
                agent_name=agent_name,
                version=version,
                snapshot_json=json.dumps(
                    {"agent_id": agent_name, "version": version, "note": note}, ensure_ascii=False
                ),
                change_note=note,
            )
        )

    def _register_with_runtime(self, row: AgentRecord, target: dict | None) -> None:
        config = AgentConfig(
            name=row.name,
            model=row.model,
            model_id=row.model_id,
            user_id=row.user_id,
            tools=json.loads(row.tools) if row.tools else [],
            system_prompt=row.system_prompt,
            description=row.description,
            memory_config=json.loads(row.memory) if row.memory else None,
            knowledge_config=json.loads(row.knowledge_config) if row.knowledge_config else None,
            policy=json.loads(row.policy) if row.policy else None,
            runtime_config=json.loads(row.runtime_config) if row.runtime_config else None,
            model_target=target,
            status=row.status or "active",
        )
        if self.runtime is not None:
            self.runtime.create_agent(config)
        if self.engine is not None:
            try:
                self.engine.create_agent(
                    name=row.name,
                    model_name=row.model,
                    tools=config.tools,
                    memory_config=config.memory_config,
                    system_prompt=row.system_prompt,
                    user_id=row.user_id,
                )
            except Exception:
                pass
