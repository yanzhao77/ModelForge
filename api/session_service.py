"""
会话管理服务
提供会话的创建、删除、切换和消息管理
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session as DBSession
from models.database_models import User, Session, Message


class SessionService:
    """会话管理服务"""
    
    @staticmethod
    def create_session(db: DBSession, user_id: int, title: str = "新对话", model_path: str = None) -> Session:
        """创建新会话"""
        new_session = Session(
            user_id=user_id,
            title=title,
            model_path=model_path,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return new_session
    
    @staticmethod
    def get_user_sessions(db: DBSession, user_id: int, include_inactive: bool = False) -> List[Session]:
        """获取用户的所有会话"""
        query = db.query(Session).filter(Session.user_id == user_id)
        if not include_inactive:
            query = query.filter(Session.is_active == True)
        return query.order_by(Session.updated_at.desc()).all()
    
    @staticmethod
    def get_session_by_id(db: DBSession, session_id: int, user_id: int = None) -> Optional[Session]:
        """根据 ID 获取会话"""
        query = db.query(Session).filter(Session.id == session_id)
        if user_id:
            query = query.filter(Session.user_id == user_id)
        return query.first()
    
    @staticmethod
    def update_session_title(db: DBSession, session_id: int, title: str, user_id: int = None) -> bool:
        """更新会话标题"""
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        session.title = title
        session.updated_at = datetime.utcnow()
        db.commit()
        return True
    
    @staticmethod
    def delete_session(db: DBSession, session_id: int, user_id: int = None) -> bool:
        """删除会话（软删除）"""
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        session.is_active = False
        session.updated_at = datetime.utcnow()
        db.commit()
        return True
    
    @staticmethod
    def hard_delete_session(db: DBSession, session_id: int, user_id: int = None) -> bool:
        """永久删除会话"""
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        db.delete(session)
        db.commit()
        return True
    
    @staticmethod
    def add_message(db: DBSession, session_id: int, role: str, content: str, token_count: int = 0) -> Message:
        """添加消息到会话"""
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
            timestamp=datetime.utcnow()
        )
        db.add(message)
        
        # 更新会话的 updated_at
        session = db.query(Session).filter(Session.id == session_id).first()
        if session:
            session.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(message)
        return message
    
    @staticmethod
    def get_session_messages(db: DBSession, session_id: int, limit: int = None) -> List[Message]:
        """获取会话的所有消息"""
        query = db.query(Message).filter(Message.session_id == session_id).order_by(Message.timestamp.asc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    @staticmethod
    def get_session_history(db: DBSession, session_id: int, limit: int = None) -> List[dict]:
        """获取会话历史（格式化为模型输入格式）"""
        messages = SessionService.get_session_messages(db, session_id, limit)
        return [msg.to_dict() for msg in messages]
    
    @staticmethod
    def clear_session_messages(db: DBSession, session_id: int, user_id: int = None) -> bool:
        """清空会话消息"""
        session = SessionService.get_session_by_id(db, session_id, user_id)
        if not session:
            return False
        db.query(Message).filter(Message.session_id == session_id).delete()
        session.updated_at = datetime.utcnow()
        db.commit()
        return True
    
    @staticmethod
    def get_session_message_count(db: DBSession, session_id: int) -> int:
        """获取会话消息数量"""
        return db.query(Message).filter(Message.session_id == session_id).count()
    
    @staticmethod
    def auto_generate_title(db: DBSession, session_id: int) -> bool:
        """
        自动生成会话标题（基于第一条用户消息）
        """
        messages = SessionService.get_session_messages(db, session_id, limit=1)
        if not messages:
            return False
        
        first_message = messages[0]
        if first_message.role == "user":
            # 截取前30个字符作为标题
            title = first_message.content[:30]
            if len(first_message.content) > 30:
                title += "..."
            return SessionService.update_session_title(db, session_id, title)
        return False
