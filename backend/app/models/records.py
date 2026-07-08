"""SQLAlchemy models for ModelForge 2.0."""
import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime

from core.database import Base


class ModelRecord(Base):
    """Represents an AI model stored locally or tracked remotely."""
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    provider = Column(String(100), nullable=False, default="local")
    path = Column(String(1024), nullable=True)
    size = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default="available")
    created_time = Column(DateTime, default=datetime.datetime.utcnow)


class AgentRecord(Base):
    """Represents an AI agent configuration."""
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    model = Column(String(255), nullable=False)
    tools = Column(Text, nullable=True)
    memory = Column(Text, nullable=True)
