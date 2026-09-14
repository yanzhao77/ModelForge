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
    UniqueConstraint,
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
    """A model asset tracked locally or from a remote provider.

    This row is the single source of truth for the model lifecycle: download,
    model center, chat, training and the OpenAI-compatible API all resolve a
    ``model_id`` (this primary key) through it instead of passing file paths or
    display names around. ``capabilities`` and ``model_metadata`` are stored as
    JSON text so the schema stays portable between SQLite and PostgreSQL.
    """
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)  # None = 全局模型
    name = Column(String(255), nullable=False, index=True)
    display_name = Column(String(255), nullable=True)
    provider = Column(String(100), nullable=False, default="local")
    path = Column(String(1024), nullable=True)
    size = Column(String(50), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    status = Column(String(50), nullable=False, default="available")
    format = Column(String(50), nullable=True)  # gguf / safetensors / ...
    quant = Column(String(50), nullable=True)  # Q4_K_M 等量化类型
    capabilities = Column(Text, nullable=True)  # JSON array, e.g. ["CHAT","INFERENCE"]
    model_metadata = Column(Text, nullable=True)  # JSON object (architecture, params, …)
    #: V1.2 multi-runtime: which adapters can serve this asset, and which one the
    #: user prefers. Both are JSON/scalar so the schema stays portable.
    supported_runtimes = Column(Text, nullable=True)  # JSON array, e.g. ["llama_cpp"]
    preferred_runtime = Column(String(64), nullable=True)
    base_model_id = Column(Integer, nullable=True)  # training artifact -> base model
    parent_model_id = Column(Integer, nullable=True)  # LoRA adapter -> full model
    created_time = Column(DateTime, default=datetime.datetime.utcnow)
    updated_time = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # -- capability helpers -------------------------------------------------

    def capability_list(self) -> list[str]:
        """Return the parsed capability list, never ``None``."""
        return _parse_json_list(self.capabilities)

    def set_capabilities(self, values: list[str]) -> None:
        import json as _json

        cleaned: list[str] = []
        for value in values or []:
            text = str(value).strip().upper()
            if text and text not in cleaned:
                cleaned.append(text)
        self.capabilities = _json.dumps(cleaned, ensure_ascii=False)

    def has_capability(self, capability: str) -> bool:
        return str(capability).strip().upper() in self.capability_list()

    def supported_runtime_list(self) -> list[str]:
        """Parsed multi-runtime list, never ``None``."""
        # Runtime ids are lower-case adapter names, unlike UPPER_CASE capabilities.
        return [item.lower() for item in _parse_json_list(self.supported_runtimes, uppercase=False)]

    def set_supported_runtimes(self, values: list[str]) -> None:
        import json as _json

        cleaned: list[str] = []
        for value in values or []:
            text = str(value).strip().lower()
            if text and text not in cleaned:
                cleaned.append(text)
        self.supported_runtimes = _json.dumps(cleaned, ensure_ascii=False)

    # -- metadata helpers ---------------------------------------------------

    def metadata_dict(self) -> dict:
        """Return the parsed metadata object, never ``None``."""
        return _parse_json_object(self.model_metadata)

    def set_metadata(self, values: dict | None) -> None:
        import json as _json

        payload = {str(key): value for key, value in (values or {}).items()}
        self.model_metadata = _json.dumps(payload, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            # ``model_id`` is the cross-module identifier required by the model
            # runtime contract; ``id`` is kept for existing desktop clients.
            "model_id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "provider": self.provider,
            "source": self.provider,
            "path": self.path,
            "size": self.size,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "format": self.format,
            "quant": self.quant,
            "capabilities": self.capability_list(),
            "supported_runtimes": self.supported_runtime_list(),
            "preferred_runtime": self.preferred_runtime,
            "metadata": self.metadata_dict(),
            "base_model_id": self.base_model_id,
            "parent_model_id": self.parent_model_id,
            "created_time": self.created_time.isoformat() if self.created_time else None,
            "updated_time": self.updated_time.isoformat() if self.updated_time else None,
        }


def _parse_json_list(value: str | None, *, uppercase: bool = True) -> list[str]:
    """Decode a JSON array column without ever raising on corrupt data."""
    import json as _json

    if not value:
        return []
    try:
        parsed = _json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    cleaned = [str(item).strip() for item in parsed if str(item).strip()]
    return [item.upper() for item in cleaned] if uppercase else cleaned


def _parse_json_object(value: str | None) -> dict:
    """Decode a JSON object column without ever raising on corrupt data."""
    import json as _json

    if not value:
        return {}
    try:
        parsed = _json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_value(value: str | None):
    """Decode any JSON value (a node output may be a string, list or number)."""
    import json as _json

    if value is None or value == "":
        return None
    try:
        return _json.loads(value)
    except (TypeError, ValueError):
        return None


class DownloadTaskRecord(Base):
    """Persisted, user-scoped model download state without host path disclosure."""
    __tablename__ = "download_tasks"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    repo_id = Column(String(255), nullable=False)
    filename = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    progress = Column(Integer, nullable=False, default=0)
    message = Column(String(255), nullable=False, default="Pending")
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_download_tasks_user_status", "user_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "task_id": self.id,
            "repo_id": self.repo_id,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error_code": self.error_code,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class AgentRecord(Base):
    """Persisted AgentDefinition (V1.1): model bound by ``model_id``."""
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    user_id = Column(Integer, nullable=True, index=True)
    model = Column(String(255), nullable=False)
    #: Stable cross-module model reference (ModelRegistry.id). Agents never hold
    #: a file path; the runtime manager resolves model_id -> path.
    model_id = Column(Integer, nullable=True, index=True)
    tools = Column(Text, nullable=True)
    memory = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="active")
    policy = Column(Text, nullable=True)  # JSON
    runtime_config = Column(Text, nullable=True)  # JSON
    knowledge_config = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    def to_dict(self) -> dict:
        import json as _json

        def _parsed_list(value: str | None) -> list:
            try:
                parsed = _json.loads(value) if value else []
            except (TypeError, ValueError):
                return []
            return parsed if isinstance(parsed, list) else []

        def _parsed_dict(value: str | None) -> dict:
            try:
                parsed = _json.loads(value) if value else {}
            except (TypeError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}

        return {
            "id": self.id,
            "agent_id": self.name,
            "name": self.name,
            "model": self.model,
            "model_id": self.model_id,
            "tools": _parsed_list(self.tools),
            "memory": _parsed_dict(self.memory),
            "system_prompt": self.system_prompt,
            "description": self.description,
            "status": self.status,
            "policy": _parsed_dict(self.policy),
            "runtime_config": _parsed_dict(self.runtime_config),
            "knowledge_config": _parsed_dict(self.knowledge_config),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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
        endpoint_suffix = "responses" if self.protocol == "responses" else "chat/completions"
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "protocol": self.protocol,
            "default_model": self.default_model,
            "enabled": self.enabled,
            "key_configured": bool(self.key_ciphertext),
            "credential_state": "configured" if self.key_ciphertext else "missing",
            "endpoint": f"{self.base_url.rstrip('/')}/{endpoint_suffix}",
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


# --------------------------------------------------------------------------
# V3.1 Multi-Agent Team
# --------------------------------------------------------------------------


class AgentTeam(Base):
    """A user-owned group of Agents coordinated by a manager Agent."""

    __tablename__ = "agent_teams"
    __table_args__ = (Index("ix_agent_teams_user_name", "user_id", "name", unique=True),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    manager_agent_id = Column(String(255), nullable=False, index=True)
    strategy = Column(String(32), nullable=False, default="SEQUENTIAL")
    max_concurrency = Column(Integer, nullable=False, default=1)
    timeout = Column(Integer, nullable=True)
    retry_policy = Column(Text, nullable=True)
    shared_memory_id = Column(String(64), nullable=True)
    permission_policy_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "team_id": self.id,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "manager_agent_id": self.manager_agent_id,
            "strategy": self.strategy,
            "max_concurrency": self.max_concurrency,
            "timeout": self.timeout,
            "retry_policy": _parse_json_object(self.retry_policy),
            "shared_memory_id": self.shared_memory_id,
            "permission_policy_id": self.permission_policy_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentTeamMember(Base):
    """A role-bound Agent inside an AgentTeam."""

    __tablename__ = "agent_team_members"
    __table_args__ = (Index("ix_agent_team_members_team_agent_role", "team_id", "agent_id", "role", unique=True),)

    id = Column(String(64), primary_key=True)
    team_id = Column(String(64), ForeignKey("agent_teams.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    config_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "config": _parse_json_object(self.config_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentTeamRun(Base):
    """One execution of an AgentTeam plan."""

    __tablename__ = "agent_team_runs"
    __table_args__ = (Index("ix_agent_team_runs_user_created", "user_id", "created_at"),)

    id = Column(String(64), primary_key=True)
    team_id = Column(String(64), ForeignKey("agent_teams.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    manager_agent_id = Column(String(255), nullable=False, index=True)
    task_id = Column(String(64), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    input = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "run_id": self.id,
            "team_id": self.team_id,
            "manager_agent_id": self.manager_agent_id,
            "task_id": self.task_id,
            "status": self.status,
            "input": self.input,
            "result": _parse_json_value(self.result_json),
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentTeamTask(Base):
    """A delegated unit of work assigned to one team member Agent."""

    __tablename__ = "agent_team_tasks"
    __table_args__ = (Index("ix_agent_team_tasks_run_sequence", "run_id", "sequence", unique=True),)

    id = Column(String(64), primary_key=True)
    team_id = Column(String(64), ForeignKey("agent_teams.id"), nullable=False, index=True)
    run_id = Column(String(64), ForeignKey("agent_team_runs.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_record_id = Column(String(64), nullable=True, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    input = Column(Text, nullable=True)
    output = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    sequence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "task_id": self.id,
            "team_id": self.team_id,
            "run_id": self.run_id,
            "task_record_id": self.task_record_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "sequence": self.sequence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class AgentDelegation(Base):
    """Explicit manager-to-member delegation record."""

    __tablename__ = "agent_delegations"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    manager_agent_id = Column(String(255), nullable=False, index=True)
    delegate_agent_id = Column(String(255), nullable=False, index=True)
    team_id = Column(String(64), nullable=True, index=True)
    team_task_id = Column(String(64), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    instruction = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "delegation_id": self.id,
            "manager_agent_id": self.manager_agent_id,
            "delegate_agent_id": self.delegate_agent_id,
            "team_id": self.team_id,
            "team_task_id": self.team_task_id,
            "status": self.status,
            "instruction": self.instruction,
            "result": _parse_json_value(self.result_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentTeamMessage(Base):
    """Message exchanged between Agents during a team run."""

    __tablename__ = "agent_team_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(64), unique=True, nullable=False, index=True)
    team_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(64), nullable=True, index=True)
    from_agent_id = Column(String(255), nullable=True, index=True)
    to_agent_id = Column(String(255), nullable=True, index=True)
    message_type = Column(String(32), nullable=False, index=True)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "team_id": self.team_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "from_agent_id": self.from_agent_id,
            "to_agent_id": self.to_agent_id,
            "message_type": self.message_type,
            "content": _parse_json_value(self.content),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentTeamEvent(Base):
    """Durable event stream for team topology, task and trace views."""

    __tablename__ = "agent_team_events"
    __table_args__ = (Index("ix_agent_team_events_run_sequence", "run_id", "sequence", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0)
    event_type = Column(String(64), nullable=False, index=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": _parse_json_object(self.payload_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# --------------------------------------------------------------------------
# V3.3 Agent Learning
# --------------------------------------------------------------------------


class AgentExperience(Base):
    """Reusable experience captured from an Agent or Team task."""

    __tablename__ = "agent_experiences"
    __table_args__ = (Index("ix_agent_experience_user_agent_created", "user_id", "agent_id", "created_at"),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    task_id = Column(String(64), nullable=True, index=True)
    goal = Column(Text, nullable=False)
    context_json = Column(Text, nullable=True)
    strategy_json = Column(Text, nullable=True)
    steps_json = Column(Text, nullable=True)
    tools_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    outcome = Column(String(32), nullable=False, default="PARTIAL_SUCCESS", index=True)
    score = Column(Float, nullable=True)
    failure_reason = Column(Text, nullable=True)
    reflection = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "experience_id": self.id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "goal": self.goal,
            "context": _parse_json_object(self.context_json),
            "strategy": _parse_json_object(self.strategy_json),
            "steps": _parse_json_value(self.steps_json) or [],
            "tools": _parse_json_value(self.tools_json) or [],
            "result": _parse_json_value(self.result_json),
            "outcome": self.outcome,
            "score": self.score,
            "failure_reason": self.failure_reason,
            "reflection": self.reflection,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ExperienceEpisode(Base):
    __tablename__ = "experience_episodes"

    id = Column(String(64), primary_key=True)
    experience_id = Column(String(64), ForeignKey("agent_experiences.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ExperienceStep(Base):
    __tablename__ = "experience_steps"
    __table_args__ = (Index("ix_experience_steps_sequence", "experience_id", "sequence", unique=True),)

    id = Column(String(64), primary_key=True)
    experience_id = Column(String(64), ForeignKey("agent_experiences.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0)
    action = Column(Text, nullable=False)
    observation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ExperienceOutcome(Base):
    __tablename__ = "experience_outcomes"

    id = Column(String(64), primary_key=True)
    experience_id = Column(String(64), ForeignKey("agent_experiences.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    outcome = Column(String(32), nullable=False)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ExperienceEvaluation(Base):
    __tablename__ = "experience_evaluations"

    id = Column(String(64), primary_key=True)
    experience_id = Column(String(64), ForeignKey("agent_experiences.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    metrics_json = Column(Text, nullable=False, default="{}")
    human_rating = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


# --------------------------------------------------------------------------
# V3.4 Autonomous Agent
# --------------------------------------------------------------------------


class Goal(Base):
    """Long-running autonomous objective owned by one Agent."""

    __tablename__ = "goals"
    __table_args__ = (Index("ix_goals_user_status_priority", "user_id", "status", "priority"),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String(16), nullable=False, default="normal")
    deadline = Column(DateTime, nullable=True)
    constraints_json = Column(Text, nullable=False, default="[]")
    success_criteria_json = Column(Text, nullable=False, default="[]")
    status = Column(String(32), nullable=False, default="CREATED", index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "goal_id": self.id,
            "agent_id": self.agent_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "constraints": _parse_json_value(self.constraints_json) or [],
            "success_criteria": _parse_json_value(self.success_criteria_json) or [],
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SubGoal(Base):
    __tablename__ = "sub_goals"
    __table_args__ = (Index("ix_sub_goals_goal_sequence", "goal_id", "sequence", unique=True),)

    id = Column(String(64), primary_key=True)
    goal_id = Column(String(64), ForeignKey("goals.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    sequence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "sub_goal_id": self.id,
            "goal_id": self.goal_id,
            "title": self.title,
            "objective": self.objective,
            "status": self.status,
            "sequence": self.sequence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ApprovalPolicy(Base):
    __tablename__ = "approval_policies"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    rules_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    goal_id = Column(String(64), nullable=True, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    action = Column(String(160), nullable=False)
    risk = Column(String(16), nullable=False, default="HIGH", index=True)
    details_json = Column(Text, nullable=False, default="{}")
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    decided_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "approval_id": self.id,
            "goal_id": self.goal_id,
            "agent_id": self.agent_id,
            "action": self.action,
            "risk": self.risk,
            "details": _parse_json_object(self.details_json),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id = Column(String(64), primary_key=True)
    approval_id = Column(String(64), ForeignKey("approval_requests.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    decision = Column(String(24), nullable=False)
    modifications_json = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "decision_id": self.id,
            "approval_id": self.approval_id,
            "decision": self.decision,
            "modifications": _parse_json_object(self.modifications_json),
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# --------------------------------------------------------------------------
# V4.0 AI Operating System core objects
# --------------------------------------------------------------------------


class OSResource(Base):
    """Unified resource index for models, agents, tools, knowledge and packages."""

    __tablename__ = "os_resources"
    __table_args__ = (Index("ix_os_resources_user_type_status", "user_id", "resource_type", "status"),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    resource_id = Column(String(160), nullable=False, index=True)
    resource_type = Column(String(48), nullable=False, index=True)
    owner = Column(String(160), nullable=True)
    permissions_json = Column(Text, nullable=False, default="[]")
    status = Column(String(32), nullable=False, default="active", index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "resource_id": self.resource_id,
            "type": self.resource_type,
            "owner": self.owner,
            "permissions": _parse_json_value(self.permissions_json) or [],
            "status": self.status,
            "metadata": _parse_json_object(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class OSProcess(Base):
    """Unified process index for runs, training, evaluation, goals and teams."""

    __tablename__ = "os_processes"
    __table_args__ = (Index("ix_os_processes_user_status_priority", "user_id", "status", "priority"),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    process_id = Column(String(160), nullable=False, index=True)
    process_type = Column(String(48), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    priority = Column(String(16), nullable=False, default="normal")
    resource_id = Column(String(160), nullable=True, index=True)
    runtime = Column(String(64), nullable=True)
    logs_json = Column(Text, nullable=True)
    trace_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "process_id": self.process_id,
            "type": self.process_type,
            "status": self.status,
            "priority": self.priority,
            "resource_id": self.resource_id,
            "runtime": self.runtime,
            "logs": _parse_json_value(self.logs_json) or [],
            "trace": _parse_json_value(self.trace_json) or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class OSEvent(Base):
    """Unified event fact table for Event OS."""

    __tablename__ = "os_events"
    __table_args__ = (Index("ix_os_events_user_type_created", "user_id", "event_type", "created_at"),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    subject_id = Column(String(160), nullable=True, index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "event_id": self.id,
            "event_type": self.event_type,
            "subject_id": self.subject_id,
            "payload": _parse_json_object(self.payload_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EventRule(Base):
    """Event -> condition -> action rule definition."""

    __tablename__ = "event_rules"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    event_type = Column(String(100), nullable=False, index=True)
    condition_json = Column(Text, nullable=False, default="{}")
    action_json = Column(Text, nullable=False, default="{}")
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.id,
            "name": self.name,
            "event_type": self.event_type,
            "condition": _parse_json_object(self.condition_json),
            "action": _parse_json_object(self.action_json),
            "enabled": bool(self.enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentSkill(Base):
    """Agent Skill = tools + prompt + knowledge + workflow + evaluation."""

    __tablename__ = "agent_skills"
    __table_args__ = (Index("ix_agent_skills_user_name", "user_id", "name", unique=True),)

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    tools_json = Column(Text, nullable=False, default="[]")
    prompt = Column(Text, nullable=True)
    knowledge_json = Column(Text, nullable=False, default="[]")
    workflow_id = Column(String(64), nullable=True)
    evaluation_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.id,
            "name": self.name,
            "description": self.description,
            "tools": _parse_json_value(self.tools_json) or [],
            "prompt": self.prompt,
            "knowledge": _parse_json_value(self.knowledge_json) or [],
            "workflow_id": self.workflow_id,
            "evaluation": _parse_json_object(self.evaluation_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
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


class VideoJob(Base):
    """Persistent source of truth for local video generation jobs."""

    __tablename__ = "video_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(String(64), nullable=False, unique=True, index=True)
    model_id = Column(String(255), nullable=False, index=True)
    runtime_name = Column(String(100), nullable=False)
    profile_id = Column(String(100), nullable=False)
    status = Column(String(32), nullable=False, default="QUEUED", index=True)
    status_detail_code = Column(String(100), nullable=True)
    progress = Column(Integer, nullable=False, default=0)
    phase = Column(String(64), nullable=False, default="accepted")
    prompt_ciphertext = Column(Text, nullable=True)
    request_json = Column(Text, nullable=False, default="{}")
    resolved_request_json = Column(Text, nullable=False, default="{}")
    idempotency_key_hash = Column(String(64), nullable=True, index=True)
    request_hash = Column(String(64), nullable=False)
    seed = Column(Integer, nullable=True)
    frames = Column(Integer, nullable=False)
    fps = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    steps = Column(Integer, nullable=False)
    worker_id = Column(String(64), nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    attempt = Column(Integer, nullable=False, default=1)
    output_relpath = Column(String(1024), nullable=True)
    output_sha256 = Column(String(64), nullable=True)
    output_bytes = Column(Integer, nullable=True)
    media_duration_ms = Column(Integer, nullable=True)
    error_code = Column(String(100), nullable=True)
    error_summary = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    queued_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key_hash", name="uq_video_jobs_user_idempotency"),
        Index("ix_video_jobs_user_status_created", "user_id", "status", "queued_at"),
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

    def to_public_dict(self) -> dict:
        status_map = {
            "QUEUED": "queued",
            "RUNNING": "processing",
            "CANCEL_REQUESTED": "processing",
            "INTERRUPTED": "failed",
            "COMPLETED": "completed",
            "FAILED": "failed",
            "CANCELLED": "cancelled",
        }
        return {
            "id": self.public_id,
            "object": "video",
            "created_at": int(self.queued_at.timestamp()) if self.queued_at else None,
            "status": status_map.get(self.status, "failed"),
            "model": self.model_id,
            "progress": int(self.progress or 0),
            "phase": self.phase,
            "resolved": self._json(self.resolved_request_json, {}),
            "status_detail": {"code": self.status_detail_code} if self.status_detail_code else None,
            "error": {"code": self.error_code, "message": self.error_summary} if self.error_code else None,
            "task_id": self.task_id,
        }


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


class Organization(Base):
    """An API customer's top-level ownership boundary."""

    __tablename__ = "organizations"
    __table_args__ = (Index("ix_organizations_owner_name", "owner_user_id", "name", unique=True),)

    id = Column(String(32), primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApiProject(Base):
    """A project-scoped API isolation and billing boundary."""

    __tablename__ = "api_projects"
    __table_args__ = (Index("ix_api_projects_org_name", "organization_id", "name", unique=True),)

    id = Column(String(32), primary_key=True)
    organization_id = Column(String(32), ForeignKey("organizations.id"), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    environment = Column(String(24), nullable=False, default="live")
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "environment": self.environment,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ProjectApiKey(Base):
    """One-way-hashed, revocable key for a single API project."""

    __tablename__ = "project_api_keys"
    __table_args__ = (Index("ix_project_api_keys_project_prefix", "project_id", "prefix", unique=True),)

    id = Column(String(32), primary_key=True)
    project_id = Column(String(32), ForeignKey("api_projects.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    prefix = Column(String(24), nullable=False, unique=True, index=True)
    secret_hash = Column(String(128), nullable=False)
    scopes_json = Column(Text, nullable=False, default="[]")
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "prefix": self.prefix,
            "scopes": _json.loads(self.scopes_json or "[]"),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApiInvocation(Base):
    """Project-scoped, idempotent API invocation receipt."""

    __tablename__ = "api_invocations"
    __table_args__ = (
        Index("ix_api_invocations_project_created", "project_id", "created_at"),
        Index("ix_api_invocations_project_status", "project_id", "status"),
        Index("ix_api_invocations_project_idempotency", "project_id", "idempotency_key", unique=True),
    )

    id = Column(String(32), primary_key=True)
    project_id = Column(String(32), ForeignKey("api_projects.id"), nullable=False, index=True)
    api_key_id = Column(String(32), ForeignKey("project_api_keys.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(128), nullable=False)
    agent_id = Column(String(255), nullable=False)
    reserved_tokens = Column(Integer, nullable=False, default=0)
    run_id = Column(String(64), nullable=True, unique=True, index=True)
    status = Column(String(24), nullable=False, default="PENDING")
    response_json = Column(Text, nullable=True)
    error_code = Column(String(96), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "idempotency_key": self.idempotency_key,
            "agent_id": self.agent_id,
            "reserved_tokens": self.reserved_tokens,
            "run_id": self.run_id,
            "status": self.status,
            "response": _json.loads(self.response_json) if self.response_json else None,
            "error_code": self.error_code,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ProjectQuota(Base):
    """Enforced project-level execution and token budgets."""

    __tablename__ = "project_quotas"

    project_id = Column(String(32), ForeignKey("api_projects.id"), primary_key=True)
    max_concurrent_runs = Column(Integer, nullable=False, default=2)
    daily_token_limit = Column(Integer, nullable=False, default=100_000)
    monthly_token_limit = Column(Integer, nullable=False, default=1_000_000)
    per_run_token_limit = Column(Integer, nullable=False, default=16_000)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "max_concurrent_runs": self.max_concurrent_runs,
            "daily_token_limit": self.daily_token_limit,
            "monthly_token_limit": self.monthly_token_limit,
            "per_run_token_limit": self.per_run_token_limit,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UsageLedger(Base):
    """Append-only billable usage fact; rows are never updated or deleted."""

    __tablename__ = "usage_ledger"
    __table_args__ = (
        Index("ix_usage_ledger_project_occurred", "project_id", "occurred_at"),
        Index("ix_usage_ledger_invocation_metric", "invocation_id", "metric_type", unique=True),
    )

    id = Column(String(32), primary_key=True)
    project_id = Column(String(32), ForeignKey("api_projects.id"), nullable=False, index=True)
    invocation_id = Column(String(32), ForeignKey("api_invocations.id"), nullable=False, index=True)
    run_id = Column(String(64), nullable=True, index=True)
    idempotency_key = Column(String(128), nullable=False)
    metric_type = Column(String(48), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_version = Column(String(48), nullable=False, default="trial-v1")
    metadata_redacted = Column(Text, nullable=False, default="{}")
    occurred_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "invocation_id": self.invocation_id,
            "run_id": self.run_id,
            "idempotency_key": self.idempotency_key,
            "metric_type": self.metric_type,
            "quantity": self.quantity,
            "unit_price_version": self.unit_price_version,
            "metadata": _json.loads(self.metadata_redacted or "{}"),
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
        }


class ProjectAgentBinding(Base):
    """Explicitly grants one user-owned Agent definition to one API project."""

    __tablename__ = "project_agent_bindings"
    __table_args__ = (Index("ix_project_agent_binding_unique", "project_id", "agent_id", unique=True),)

    id = Column(String(32), primary_key=True)
    project_id = Column(String(32), ForeignKey("api_projects.id"), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "agent_id": self.agent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# --------------------------------------------------------------------------
# V1.5 Workflow / Multi-Agent
# --------------------------------------------------------------------------


class Workflow(Base):
    """A task-orchestration definition (nodes / edges / variables)."""

    __tablename__ = "workflows"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    #: Full graph as JSON: nodes, edges, variables, input/output schema.
    definition_json = Column(Text, nullable=False, default="{}")
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False
    )

    def definition(self) -> dict:
        return _parse_json_object(self.definition_json)

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.id,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "definition": self.definition(),
            "version": self.version,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkflowRun(Base):
    """One execution of a Workflow."""

    __tablename__ = "workflow_runs"

    id = Column(String(32), primary_key=True)
    workflow_id = Column(String(32), ForeignKey("workflows.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="PENDING", index=True)
    input_json = Column(Text, nullable=True)
    output_json = Column(Text, nullable=True)
    #: Per-node results + variables (the run's working memory).
    state_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    current_node = Column(String(120), nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "run_id": self.id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "input": _parse_json_object(self.input_json),
            "output": _parse_json_value(self.output_json),
            "state": _parse_json_object(self.state_json),
            "error": self.error,
            "current_node": self.current_node,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WorkflowRunEvent(Base):
    """Durable per-run event stream (node lifecycle, approvals, errors)."""

    __tablename__ = "workflow_run_events"
    __table_args__ = (Index("ix_workflow_run_event_seq", "run_id", "sequence", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(32), ForeignKey("workflow_runs.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": _parse_json_object(self.payload_json),
            "timestamp": self.created_at.isoformat() if self.created_at else None,
        }


# --------------------------------------------------------------------------
# V1.7 Packages / V1.8 Evaluation
# --------------------------------------------------------------------------


class PlatformPackage(Base):
    """An exported/imported ModelForge package (model/agent/tool/workflow)."""

    __tablename__ = "platform_packages"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    package_id = Column(String(160), nullable=False, index=True)
    kind = Column(String(24), nullable=False, index=True)
    version = Column(String(40), nullable=False, default="1.0.0")
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    license = Column(String(120), nullable=True)
    manifest_json = Column(Text, nullable=False, default="{}")
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_dict(self, *, include_payload: bool = False) -> dict:
        payload = {
            "package_id": self.package_id,
            "kind": self.kind,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "license": self.license,
            "manifest": _parse_json_object(self.manifest_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_payload:
            payload["payload"] = _parse_json_object(self.payload_json)
        return payload


class EvaluationDataset(Base):
    """A named set of evaluation cases."""

    __tablename__ = "evaluation_datasets"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    cases_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def cases(self) -> list:
        import json as _json

        try:
            parsed = _json.loads(self.cases_json or "[]")
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    def to_dict(self) -> dict:
        return {
            "evaluation_id": self.id,
            "name": self.name,
            "description": self.description,
            "case_count": len(self.cases()),
            "cases": self.cases(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvaluationRun(Base):
    """One evaluation of an Agent/Workflow against a dataset."""

    __tablename__ = "evaluation_runs"

    id = Column(String(32), primary_key=True)
    evaluation_id = Column(String(32), ForeignKey("evaluation_datasets.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_kind = Column(String(24), nullable=False, default="agent")
    target_id = Column(String(160), nullable=False)
    status = Column(String(24), nullable=False, default="PENDING", index=True)
    metrics_json = Column(Text, nullable=True)
    results_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    def results(self) -> list:
        import json as _json

        try:
            parsed = _json.loads(self.results_json or "[]")
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    def to_dict(self) -> dict:
        return {
            "run_id": self.id,
            "evaluation_id": self.evaluation_id,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "status": self.status,
            "metrics": _parse_json_object(self.metrics_json),
            "results": self.results(),
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
