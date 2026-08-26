"""SQLAlchemy models for ModelForge 2.0 (unified schema).

Merges the legacy desktop-app schema (users/sessions/messages/memories) with
the new-architecture records (models/agents). All user-scoped tables carry
a user_id column for data isolation.
"""
import datetime

from core.database import Base
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship


class User(Base):
    """User account."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("Memory", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Session(Base):
    """A conversation session belonging to a user."""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), default="新对话")
    model_id = Column(Integer, nullable=True)  # 关联的模型记录
    is_active = Column(Boolean, default=True)  # 软删除标记
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    """A single chat message inside a session."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    token_count = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    session = relationship("Session", back_populates="messages")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "token_count": self.token_count,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class Memory(Base):
    """Cross-session user memory entry."""
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    memory_type = Column(String(50), nullable=False)  # preference / fact / context / skill
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    source_session_id = Column(Integer, nullable=True)
    importance = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_accessed = Column(DateTime, default=datetime.datetime.utcnow)
    access_count = Column(Integer, default=0)

    user = relationship("User", back_populates="memories")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.memory_type,
            "key": self.key,
            "value": self.value,
            "importance": self.importance,
            "source_session_id": self.source_session_id,
            "access_count": self.access_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ModelRecord(Base):
    """A model tracked locally or from a remote provider."""
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)  # None = 全局模型
    name = Column(String(255), nullable=False, index=True)
    provider = Column(String(100), nullable=False, default="local")
    path = Column(String(1024), nullable=True)
    size = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default="available")
    format = Column(String(50), nullable=True)  # gguf / safetensors / ...
    quant = Column(String(50), nullable=True)  # Q4_K_M 等量化类型
    created_time = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "path": self.path,
            "size": self.size,
            "status": self.status,
            "format": self.format,
            "quant": self.quant,
            "created_time": self.created_time.isoformat() if self.created_time else None,
        }


class AgentRecord(Base):
    """Persisted AI agent configuration."""
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    user_id = Column(Integer, nullable=True, index=True)
    model = Column(String(255), nullable=False)
    tools = Column(Text, nullable=True)
    memory = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="active")
    policy = Column(Text, nullable=True)  # JSON
    runtime_config = Column(Text, nullable=True)  # JSON
    knowledge_config = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "tools": self.tools,
            "memory": self.memory,
            "system_prompt": self.system_prompt,
            "description": self.description,
            "status": self.status,
            "policy": _json.loads(self.policy) if self.policy else {},
            "runtime_config": _json.loads(self.runtime_config) if self.runtime_config else {},
            "knowledge_config": _json.loads(self.knowledge_config) if self.knowledge_config else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RemoteProviderConfig(Base):
    """Encrypted per-user credentials for OpenAI-compatible remote providers."""
    __tablename__ = "remote_provider_configs"
    __table_args__ = (Index("ix_remote_provider_user_name", "user_id", "name", unique=True),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    base_url = Column(String(512), nullable=False)
    protocol = Column(String(32), nullable=False, default="responses")
    default_model = Column(String(255), nullable=False)
    key_ciphertext = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_verified_at = Column(DateTime, nullable=True)
    verification_status = Column(String(32), nullable=False, default="unknown")
    verification_error_code = Column(String(64), nullable=True)
    verified_models_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "protocol": self.protocol,
            "default_model": self.default_model,
            "enabled": self.enabled,
            "key_configured": bool(self.key_ciphertext),
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "verification_status": self.verification_status or "unknown",
            "verification_error_code": self.verification_error_code,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentTemplate(Base):
    """User-owned, credential-free Agent definition template."""

    __tablename__ = "agent_templates"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    definition_json = Column(Text, nullable=False, default="{}")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "definition": _json.loads(self.definition_json or "{}"),
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentDefinitionVersion(Base):
    """Immutable snapshot used to explain a historical Agent Run."""

    __tablename__ = "agent_definition_versions"
    __table_args__ = (Index("ix_agent_definition_version", "user_id", "agent_name", "version", unique=True),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_name = Column(String(255), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False, default="{}")
    change_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json

        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "version": self.version,
            "snapshot": _json.loads(self.snapshot_json or "{}"),
            "change_note": self.change_note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserModelPreference(Base):
    """One explicit default model target per user, without provider credentials."""

    __tablename__ = "user_model_preferences"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    default_kind = Column(String(32), nullable=False)
    default_model_ref = Column(String(255), nullable=False)
    default_provider_id = Column(Integer, ForeignKey("remote_provider_configs.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ApiKey(Base):
    """API key for the OpenAI-compatible endpoint."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    key_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }



class Dataset(Base):
    """A training dataset uploaded by a user (jsonl/csv/json/txt)."""
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    file_path = Column(String(1024), nullable=False)
    original_name = Column(String(255), nullable=False)
    format = Column(String(20), nullable=False)  # jsonl / csv / json / txt
    row_count = Column(Integer, default=0)
    file_size = Column(Integer, default=0)
    columns = Column(Text, nullable=True)  # JSON list
    sample = Column(Text, nullable=True)  # JSON preview (first rows)
    status = Column(String(20), default="uploaded")  # uploaded / parsed / error
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "name": self.name,
            "format": self.format,
            "row_count": self.row_count,
            "file_size": self.file_size,
            "columns": _json.loads(self.columns) if self.columns else [],
            "sample": _json.loads(self.sample) if self.sample else [],
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TrainTask(Base):
    """A persisted fine-tuning task (full / LoRA)."""
    __tablename__ = "train_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(32), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(Integer, nullable=True)
    base_model = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False, default="lora")
    config = Column(Text, nullable=True)  # JSON snapshot
    status = Column(String(20), default="pending")  # pending/running/stopped/done/error
    progress = Column(Float, default=0.0)
    current_epoch = Column(Integer, default=0)
    total_epochs = Column(Integer, default=0)
    loss = Column(Float, nullable=True)
    output_dir = Column(String(1024), nullable=True)
    log_path = Column(String(1024), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "task_id": self.task_id,
            "base_model": self.base_model,
            "method": self.method,
            "dataset_id": self.dataset_id,
            "status": self.status,
            "progress": round(self.progress or 0, 1),
            "current_epoch": self.current_epoch,
            "total_epochs": self.total_epochs,
            "loss": self.loss,
            "output_dir": self.output_dir,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "config": _json.loads(self.config) if self.config else {},
        }


class KnowledgeDocument(Base):
    """Knowledge base document index."""
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False, index=True)
    filetype = Column(String(20), nullable=False, default="text")
    chunk_count = Column(Integer, default=0)
    doc_meta = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "filename": self.filename,
            "filetype": self.filetype,
            "chunk_count": self.chunk_count,
            "doc_meta": _json.loads(self.doc_meta) if self.doc_meta else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KnowledgeChunk(Base):
    """A chunk of a knowledge base document."""
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    chunk_index = Column(Integer, default=0)
    content = Column(Text, nullable=False)
    meta = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "content": self.content[:300],
            "metadata": _json.loads(self.meta) if self.meta else {},
        }


class AgentRun(Base):
    """ModelForge 3.0: a persisted execution of an agent (Run)."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    session_id = Column(Integer, nullable=True, index=True)
    parent_run_id = Column(String(64), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    state_version = Column(Integer, nullable=False, default=1)
    executor_lease_id = Column(String(64), nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    terminal_event_key = Column(String(128), nullable=True)
    input = Column(Text, nullable=True)
    output = Column(Text, nullable=True)
    model = Column(String(255), nullable=True)
    error = Column(Text, nullable=True)
    token_usage = Column(Text, nullable=True)  # JSON {prompt, completion, total}
    tool_call_count = Column(Integer, default=0)
    iteration_count = Column(Integer, default=0)
    meta = Column(Text, nullable=True)  # JSON metadata
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
        Index("ix_agent_runs_status_lease", "status", "lease_expires_at"),
        Index("ix_agent_runs_terminal_event_key", "terminal_event_key", unique=True),
    )

    def to_dict(self) -> dict:
        import json as _json
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "parent_run_id": self.parent_run_id,
            "status": self.status,
            "state_version": self.state_version or 1,
            "input": self.input,
            "output": self.output,
            "model": self.model,
            "error": self.error,
            "token_usage": _json.loads(self.token_usage) if self.token_usage else {},
            "tool_call_count": self.tool_call_count or 0,
            "iteration_count": self.iteration_count or 0,
            "metadata": _json.loads(self.meta) if self.meta else {},
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentEventRecord(Base):
    """ModelForge 3.0: a persisted agent run event (Event is the fact)."""
    __tablename__ = "agent_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    sequence = Column(Integer, nullable=False, default=0)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    payload = Column(Text, nullable=True)  # JSON
    correlation_id = Column(String(64), nullable=True)
    event_key = Column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_agent_events_run_seq", "run_id", "sequence"),
        Index("ix_agent_events_run_key", "run_id", "event_key", unique=True),
    )

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "payload": _json.loads(self.payload) if self.payload else {},
            "correlation_id": self.correlation_id,
            "event_key": self.event_key,
        }


class ToolRecord(Base):
    """ModelForge 3.0: a registered tool (builtin / plugin / MCP)."""
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    version = Column(String(50), default="1.0.0")
    input_schema = Column(Text, nullable=True)  # JSON
    permissions = Column(Text, nullable=True)  # JSON list of permission levels
    timeout = Column(Integer, default=60)
    retry_policy = Column(Text, nullable=True)  # JSON
    source = Column(String(50), default="builtin")  # builtin / plugin / mcp
    enabled = Column(Boolean, default=True)
    user_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_schema": _json.loads(self.input_schema) if self.input_schema else {},
            "permissions": _json.loads(self.permissions) if self.permissions else [],
            "timeout": self.timeout,
            "retry_policy": _json.loads(self.retry_policy) if self.retry_policy else {},
            "source": self.source,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class TaskRecord(Base):
    """A user-owned, persisted projection of any long-running product task."""
    __tablename__ = "task_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    parent_task_id = Column(String(64), nullable=True, index=True)
    task_type = Column(String(64), nullable=False, index=True)
    source = Column(String(64), nullable=False, index=True)
    source_task_id = Column(String(64), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="QUEUED", index=True)
    progress_current = Column(Integer, nullable=True)
    progress_total = Column(Integer, nullable=True)
    progress_unit = Column(String(32), nullable=True)
    progress_percent = Column(Integer, nullable=True)
    priority = Column(String(16), nullable=False, default="normal")
    cancelable = Column(Boolean, nullable=False, default=False)
    retryable = Column(Boolean, nullable=False, default=False)
    attempt = Column(Integer, nullable=False, default=1)
    max_attempts = Column(Integer, nullable=False, default=1)
    required_action = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    error_detail = Column(Text, nullable=True)
    meta = Column(Text, nullable=True)
    idempotency_key = Column(String(128), nullable=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_task_records_user_status_updated", "user_id", "status", "updated_at"),
        Index("ix_task_records_source_external", "source", "source_task_id"),
    )

    @staticmethod
    def _json(value, fallback):
        import json as _json
        if not value:
            return fallback
        try:
            return _json.loads(value)
        except (TypeError, ValueError):
            return fallback

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "task_type": self.task_type,
            "source": self.source,
            "source_task_id": self.source_task_id,
            "title": self.title,
            "summary": self.summary,
            "status": self.status,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "progress_unit": self.progress_unit,
            "progress_percent": self.progress_percent,
            "priority": self.priority,
            "cancelable": bool(self.cancelable),
            "retryable": bool(self.retryable),
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "required_action": self._json(self.required_action, None),
            "result": self._json(self.result, None),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "error_detail": self._json(self.error_detail, None),
            "metadata": self._json(self.meta, {}),
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TaskEvent(Base):
    """Immutable audit/event stream for task center projections and recovery."""
    __tablename__ = "task_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        import json as _json
        try:
            payload = _json.loads(self.payload or "{}")
        except (TypeError, ValueError):
            payload = {}
        return {
            "event_id": self.id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "version": self.version,
            "payload": payload,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TaskOutbox(Base):
    """Transactional outbox entry used to wake realtime task stream consumers."""
    __tablename__ = "task_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("task_events.id"), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    dispatched_at = Column(DateTime, nullable=True, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    lease_token = Column(String(64), nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    next_attempt_at = Column(DateTime, nullable=True, index=True)


class ScheduledJob(Base):
    """User-owned, persistent Agent Run schedule definition."""

    __tablename__ = "scheduled_jobs"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False, index=True)
    schedule_kind = Column(String(24), nullable=False)  # once / interval / daily / weekly
    delay_seconds = Column(Float, nullable=True)
    interval_seconds = Column(Float, nullable=True)
    timezone = Column(String(64), nullable=False, default="UTC")
    schedule_config = Column(Text, nullable=False, default="{}")
    misfire_policy = Column(String(24), nullable=False, default="skip")
    run_spec = Column(Text, nullable=False, default="{}")
    concurrency_policy = Column(String(24), nullable=False, default="skip")
    max_failures = Column(Integer, nullable=False, default=3)
    failure_count = Column(Integer, nullable=False, default=0)
    runtime_job_id = Column(String(64), nullable=True, index=True)
    pending_trigger = Column(Boolean, nullable=False, default=False)
    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json

        return {
            "id": self.id,
            "name": self.name,
            "enabled": bool(self.enabled),
            "schedule_kind": self.schedule_kind,
            "delay_seconds": self.delay_seconds,
            "interval_seconds": self.interval_seconds,
            "timezone": self.timezone,
            "schedule_config": _json.loads(self.schedule_config or "{}"),
            "misfire_policy": self.misfire_policy,
            "run_spec": _json.loads(self.run_spec or "{}"),
            "concurrency_policy": self.concurrency_policy,
            "max_failures": self.max_failures,
            "failure_count": self.failure_count,
            "pending_trigger": bool(self.pending_trigger),
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ScheduleExecution(Base):
    """Audit link between a persistent schedule and an Agent Run."""

    __tablename__ = "schedule_executions"

    id = Column(String(64), primary_key=True)
    schedule_id = Column(String(64), ForeignKey("scheduled_jobs.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_run_id = Column(String(64), nullable=True, index=True)
    trigger_kind = Column(String(24), nullable=False, default="schedule")
    occurrence_key = Column(String(160), nullable=True)
    claim_token = Column(String(64), nullable=True, index=True)
    claim_expires_at = Column(DateTime, nullable=True, index=True)
    state_version = Column(Integer, nullable=False, default=1)
    attempt_count = Column(Integer, nullable=False, default=0)
    outcome = Column(String(32), nullable=False, default="triggered")
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_schedule_execution_occurrence", "schedule_id", "occurrence_key", unique=True),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "agent_run_id": self.agent_run_id,
            "trigger_kind": self.trigger_kind,
            "occurrence_key": self.occurrence_key,
            "state_version": self.state_version or 1,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class RunArtifact(Base):
    """User-owned, redacted output package linked to an existing source record."""

    __tablename__ = "run_artifacts"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_kind = Column(String(48), nullable=False, index=True)
    source_id = Column(String(128), nullable=False, index=True)
    artifact_type = Column(String(48), nullable=False)
    title = Column(String(255), nullable=False)
    content_json = Column(Text, nullable=True)
    content_text = Column(Text, nullable=True)
    redacted = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class KnowledgeCollection(Base):
    __tablename__ = "knowledge_collections"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KnowledgeCollectionDocument(Base):
    __tablename__ = "knowledge_collection_documents"
    __table_args__ = (Index("ix_collection_document", "collection_id", "document_id", unique=True),)

    id = Column(String(64), primary_key=True)
    collection_id = Column(String(64), ForeignKey("knowledge_collections.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class PluginProfile(Base):
    __tablename__ = "plugin_profiles"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    profile_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ModelMetricBucket(Base):
    __tablename__ = "model_metric_buckets"
    __table_args__ = (Index("ix_model_metric_user_bucket", "user_id", "model_ref", "bucket_start", unique=True),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    model_ref = Column(String(255), nullable=False, index=True)
    bucket_start = Column(DateTime, nullable=False, index=True)
    request_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    error_4xx_count = Column(Integer, nullable=False, default=0)
    error_429_count = Column(Integer, nullable=False, default=0)
    error_5xx_count = Column(Integer, nullable=False, default=0)
    timeout_count = Column(Integer, nullable=False, default=0)
    latency_sum_ms = Column(Float, nullable=False, default=0.0)
    input_tokens_estimate = Column(Integer, nullable=False, default=0)
    output_tokens_estimate = Column(Integer, nullable=False, default=0)
    cost_estimate = Column(Float, nullable=False, default=0.0)


class RunMetricEmission(Base):
    """Idempotency record for one terminal Run metric aggregation attempt."""

    __tablename__ = "run_metric_emissions"

    id = Column(String(64), primary_key=True)
    emission_key = Column(String(160), nullable=False, unique=True, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    state_version = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class ModelInsightPreference(Base):
    """User-editable, non-secret price metadata and notification-only budgets."""

    __tablename__ = "model_insight_preferences"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    prices_json = Column(Text, nullable=False, default="{}")
    daily_budget = Column(Float, nullable=True)
    weekly_budget = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def price_table(self) -> dict:
        import json as _json
        try:
            value = _json.loads(self.prices_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    def estimate_cost(self, model_ref: str, input_tokens: int, output_tokens: int) -> float:
        item = self.price_table().get(model_ref)
        if not isinstance(item, dict):
            return 0.0
        try:
            return round((input_tokens * float(item.get("input_per_million", 0)) + output_tokens * float(item.get("output_per_million", 0))) / 1_000_000, 8)
        except (TypeError, ValueError):
            return 0.0

    def to_dict(self) -> dict:
        return {
            "prices": self.price_table(),
            "daily_budget": self.daily_budget,
            "weekly_budget": self.weekly_budget,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class OperationAudit(Base):
    """Redacted audit metadata for user-initiated control-plane mutations."""

    __tablename__ = "operation_audits"
    __table_args__ = (Index("ix_operation_audit_user_created", "user_id", "created_at"),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    object_type = Column(String(100), nullable=False)
    object_id = Column(String(255), nullable=False, index=True)
    correlation_id = Column(String(64), nullable=False, index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
