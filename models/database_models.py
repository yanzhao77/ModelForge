"""
数据库模型定义
支持用户管理、会话管理、消息存储和记忆系统
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """用户表"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # 关系
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("Memory", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}')>"


class Session(Base):
    """会话表 - 每个用户可以有多个对话会话"""
    __tablename__ = 'sessions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    title = Column(String(200), default="新对话")
    model_path = Column(String(500), nullable=True)  # 使用的模型路径
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)  # 是否激活
    
    # 关系
    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Session(id={self.id}, title='{self.title}', user_id={self.user_id})>"


class Message(Base):
    """消息表 - 存储每个会话中的消息"""
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user' 或 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    token_count = Column(Integer, default=0)  # 消息的 token 数量
    
    # 关系
    session = relationship("Session", back_populates="messages")
    
    def __repr__(self):
        return f"<Message(id={self.id}, role='{self.role}', session_id={self.session_id})>"
    
    def to_dict(self):
        """转换为字典格式，用于模型推理"""
        return {
            "role": self.role,
            "content": self.content
        }


class Memory(Base):
    """记忆表 - 存储用户的跨会话记忆"""
    __tablename__ = 'memories'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    memory_type = Column(String(50), nullable=False)  # 'preference', 'fact', 'context' 等
    key = Column(String(200), nullable=False)  # 记忆的关键词
    value = Column(Text, nullable=False)  # 记忆内容
    source_session_id = Column(Integer, ForeignKey('sessions.id'), nullable=True)  # 来源会话
    importance = Column(Float, default=1.0)  # 重要性评分 0-1
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed = Column(DateTime, default=datetime.utcnow)
    access_count = Column(Integer, default=0)  # 访问次数
    
    # 关系
    user = relationship("User", back_populates="memories")
    
    def __repr__(self):
        return f"<Memory(id={self.id}, type='{self.memory_type}', key='{self.key}')>"
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.memory_type,
            "key": self.key,
            "value": self.value,
            "importance": self.importance,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class ModelConfig(Base):
    """模型配置表 - 存储用户的模型配置"""
    __tablename__ = 'model_configs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    model_path = Column(String(500), nullable=False)
    model_name = Column(String(200), nullable=False)
    model_type = Column(String(50), nullable=False)  # 'safetensors' 或 'gguf'
    max_new_tokens = Column(Integer, default=2048)
    temperature = Column(Float, default=0.7)
    top_k = Column(Integer, default=50)
    repetition_penalty = Column(Float, default=1.2)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<ModelConfig(id={self.id}, model_name='{self.model_name}')>"
