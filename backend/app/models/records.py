"""SQLAlchemy models for ModelForge 2.0 (unified schema).

Merges the legacy desktop-app schema (users/sessions/messages/memories) with
the new-architecture records (models/agents). All user-scoped tables carry
a user_id column for data isolation.
"""
import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship

from core.database import Base


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

    __table_args__ = (Index("ix_agent_runs_user_created", "user_id", "created_at"),)

    def to_dict(self) -> dict:
        import json as _json
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "parent_run_id": self.parent_run_id,
            "status": self.status,
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

    __table_args__ = (Index("ix_agent_events_run_seq", "run_id", "sequence"),)

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