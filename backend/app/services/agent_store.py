"""AgentStore adapter: AgentEngine (in-memory, 2.1 compat) + agents table (3.0 persistence)."""
from __future__ import annotations

import builtins
import json
from typing import Any

from core.database import SessionLocal
from models.records import AgentRecord
from runtime.types import AgentConfig


class DBAgentStore:
    """Resolves agent definitions from the 2.1 engine first, DB second."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    @staticmethod
    def _from_engine(a: dict) -> AgentConfig:
        return AgentConfig(
            name=a["name"],
            model=a.get("model", ""),
            tools=list(a.get("tools") or []),
            plugins=list(a.get("plugins") or []),
            system_prompt=a.get("system_prompt"),
            memory_config=a.get("memory") or {"type": "conversation"},
        )

    @staticmethod
    def _from_row(row: AgentRecord) -> AgentConfig:
        return AgentConfig(
            name=row.name,
            model=row.model,
            user_id=row.user_id,
            tools=json.loads(row.tools) if row.tools else [],
            system_prompt=row.system_prompt,
            description=row.description,
            memory_config=json.loads(row.memory) if row.memory else None,
            knowledge_config=json.loads(row.knowledge_config) if row.knowledge_config else None,
            policy=json.loads(row.policy) if row.policy else None,
            runtime_config=json.loads(row.runtime_config) if row.runtime_config else None,
            plugins=(json.loads(row.runtime_config) if row.runtime_config else {}).get("plugins", []),
            status=row.status or "active",
        )

    def get(self, name: str, user_id: int | None = None) -> AgentConfig | None:
        # DB row first: it carries the full 3.0 config (policy, runtime_config,
        # knowledge_config). The in-memory engine entry is the fallback.
        with SessionLocal() as db:
            query = db.query(AgentRecord).filter(AgentRecord.name == name)
            if user_id is not None:
                query = query.filter(AgentRecord.user_id == user_id)
            row = query.first()
            if row is not None:
                return self._from_row(row)
        # Legacy in-memory definitions carry no owner and must never be exposed
        # through a user-scoped request.
        if user_id is None and self._engine is not None:
            a = self._engine.get_agent(name)
            if a is not None:
                return self._from_engine(a)
        return None

    def create(self, config: AgentConfig) -> AgentConfig:
        with SessionLocal() as db:
            row = db.query(AgentRecord).filter(AgentRecord.name == config.name).first()
            if row is not None and row.user_id != config.user_id:
                raise PermissionError("Agent name is already owned by another user")
            if row is None:
                row = AgentRecord(name=config.name)
                db.add(row)
            row.model = config.model
            row.user_id = config.user_id
            row.tools = json.dumps(config.tools, ensure_ascii=False) if config.tools else None
            row.system_prompt = config.system_prompt
            row.description = config.description
            row.memory = json.dumps(config.memory_config or {}, ensure_ascii=False) if config.memory_config else None
            row.knowledge_config = json.dumps(config.knowledge_config or {}, ensure_ascii=False) if config.knowledge_config else None
            row.policy = json.dumps(config.policy or {}, ensure_ascii=False) if config.policy else None
            rc = dict(config.runtime_config or {})
            if config.plugins:
                rc["plugins"] = list(config.plugins)
            row.runtime_config = json.dumps(rc, ensure_ascii=False) if rc else None
            row.status = config.status or "active"
            db.commit()
        return config

    def list(self, user_id: int | None = None) -> builtins.list[AgentConfig]:
        out: list[AgentConfig] = []
        seen = set()
        if user_id is None and self._engine is not None:
            for a in self._engine.list_agents():
                cfg = self._from_engine(a)
                out.append(cfg)
                seen.add(cfg.name)
        with SessionLocal() as db:
            query = db.query(AgentRecord)
            if user_id is not None:
                query = query.filter(AgentRecord.user_id == user_id)
            for row in query.order_by(AgentRecord.created_at.desc()).all():
                if row.name in seen:
                    continue
                out.append(self._from_row(row))
        return out

    def delete(self, name: str, user_id: int | None = None) -> bool:
        deleted = False
        with SessionLocal() as db:
            query = db.query(AgentRecord).filter(AgentRecord.name == name)
            if user_id is not None:
                query = query.filter(AgentRecord.user_id == user_id)
            row = query.first()
            if row is not None:
                db.delete(row)
                db.commit()
                deleted = True
        if deleted and self._engine is not None and hasattr(self._engine, "delete_agent"):
            self._engine.delete_agent(name)
        return deleted