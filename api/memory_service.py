"""
记忆管理服务
实现跨会话的智能记忆提取、存储和检索
"""
import re
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy.orm import Session as DBSession
from models.database_models import Memory, Message, Session


class MemoryService:
    """记忆管理服务"""
    
    # 记忆类型定义
    MEMORY_TYPE_PREFERENCE = "preference"  # 用户偏好
    MEMORY_TYPE_FACT = "fact"  # 事实信息
    MEMORY_TYPE_CONTEXT = "context"  # 上下文信息
    MEMORY_TYPE_SKILL = "skill"  # 技能/知识
    
    # 记忆提取关键词
    PREFERENCE_KEYWORDS = ["喜欢", "不喜欢", "偏好", "习惯", "倾向", "更喜欢", "讨厌"]
    FACT_KEYWORDS = ["我是", "我在", "我的", "我叫", "我住在", "我来自", "我的工作是"]
    
    @staticmethod
    def create_memory(
        db: DBSession,
        user_id: int,
        memory_type: str,
        key: str,
        value: str,
        source_session_id: int = None,
        importance: float = 1.0
    ) -> Memory:
        """创建新记忆"""
        # 检查是否已存在相同的记忆
        existing = db.query(Memory).filter(
            Memory.user_id == user_id,
            Memory.memory_type == memory_type,
            Memory.key == key
        ).first()
        
        if existing:
            # 更新现有记忆
            existing.value = value
            existing.importance = max(existing.importance, importance)
            existing.last_accessed = datetime.utcnow()
            existing.access_count += 1
            db.commit()
            db.refresh(existing)
            return existing
        
        # 创建新记忆
        memory = Memory(
            user_id=user_id,
            memory_type=memory_type,
            key=key,
            value=value,
            source_session_id=source_session_id,
            importance=importance,
            created_at=datetime.utcnow(),
            last_accessed=datetime.utcnow(),
            access_count=0
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory
    
    @staticmethod
    def get_user_memories(
        db: DBSession,
        user_id: int,
        memory_type: str = None,
        limit: int = None
    ) -> List[Memory]:
        """获取用户的记忆"""
        query = db.query(Memory).filter(Memory.user_id == user_id)
        if memory_type:
            query = query.filter(Memory.memory_type == memory_type)
        query = query.order_by(Memory.importance.desc(), Memory.last_accessed.desc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    @staticmethod
    def search_memories(db: DBSession, user_id: int, keyword: str, limit: int = 5) -> List[Memory]:
        """搜索相关记忆"""
        from sqlalchemy import or_
        memories = db.query(Memory).filter(
            Memory.user_id == user_id,
            or_(
                Memory.key.contains(keyword),
                Memory.value.contains(keyword)
            )
        ).order_by(Memory.importance.desc()).limit(limit).all()
        
        # 更新访问记录
        for memory in memories:
            memory.last_accessed = datetime.utcnow()
            memory.access_count += 1
        db.commit()
        
        return memories
    
    @staticmethod
    def extract_memories_from_message(
        db: DBSession,
        user_id: int,
        message_content: str,
        session_id: int = None
    ) -> List[Memory]:
        """
        从消息中提取记忆
        使用规则和关键词匹配
        """
        extracted_memories = []
        
        # 提取偏好类记忆
        for keyword in MemoryService.PREFERENCE_KEYWORDS:
            if keyword in message_content:
                # 提取包含关键词的句子
                sentences = re.split(r'[。！？\n]', message_content)
                for sentence in sentences:
                    if keyword in sentence:
                        memory = MemoryService.create_memory(
                            db=db,
                            user_id=user_id,
                            memory_type=MemoryService.MEMORY_TYPE_PREFERENCE,
                            key=keyword,
                            value=sentence.strip(),
                            source_session_id=session_id,
                            importance=0.8
                        )
                        extracted_memories.append(memory)
        
        # 提取事实类记忆
        for keyword in MemoryService.FACT_KEYWORDS:
            if keyword in message_content:
                sentences = re.split(r'[。！？\n]', message_content)
                for sentence in sentences:
                    if keyword in sentence:
                        memory = MemoryService.create_memory(
                            db=db,
                            user_id=user_id,
                            memory_type=MemoryService.MEMORY_TYPE_FACT,
                            key=keyword,
                            value=sentence.strip(),
                            source_session_id=session_id,
                            importance=0.9
                        )
                        extracted_memories.append(memory)
        
        return extracted_memories
    
    @staticmethod
    def get_relevant_memories_for_query(
        db: DBSession,
        user_id: int,
        query: str,
        limit: int = 3
    ) -> List[Memory]:
        """
        根据查询获取相关记忆
        """
        # 提取查询中的关键词
        keywords = re.findall(r'[\u4e00-\u9fa5a-zA-Z]+', query)
        
        all_memories = []
        for keyword in keywords[:5]:  # 限制关键词数量
            memories = MemoryService.search_memories(db, user_id, keyword, limit=2)
            all_memories.extend(memories)
        
        # 去重并按重要性排序
        unique_memories = {m.id: m for m in all_memories}.values()
        sorted_memories = sorted(unique_memories, key=lambda x: x.importance, reverse=True)
        
        return sorted_memories[:limit]
    
    @staticmethod
    def format_memories_for_context(memories: List[Memory]) -> str:
        """
        将记忆格式化为上下文字符串
        """
        if not memories:
            return ""
        
        context_parts = ["[用户记忆]"]
        for memory in memories:
            context_parts.append(f"- {memory.value}")
        
        return "\n".join(context_parts)
    
    @staticmethod
    def delete_memory(db: DBSession, memory_id: int, user_id: int = None) -> bool:
        """删除记忆"""
        query = db.query(Memory).filter(Memory.id == memory_id)
        if user_id:
            query = query.filter(Memory.user_id == user_id)
        memory = query.first()
        if not memory:
            return False
        db.delete(memory)
        db.commit()
        return True
    
    @staticmethod
    def update_memory_importance(db: DBSession, memory_id: int, importance: float) -> bool:
        """更新记忆重要性"""
        memory = db.query(Memory).filter(Memory.id == memory_id).first()
        if not memory:
            return False
        memory.importance = max(0.0, min(1.0, importance))  # 限制在 0-1 之间
        db.commit()
        return True
    
    @staticmethod
    def cleanup_old_memories(db: DBSession, user_id: int, keep_count: int = 100) -> int:
        """
        清理旧记忆，保留最重要的记忆
        返回删除的记忆数量
        """
        all_memories = db.query(Memory).filter(Memory.user_id == user_id).order_by(
            Memory.importance.desc(),
            Memory.last_accessed.desc()
        ).all()
        
        if len(all_memories) <= keep_count:
            return 0
        
        to_delete = all_memories[keep_count:]
        deleted_count = 0
        for memory in to_delete:
            db.delete(memory)
            deleted_count += 1
        
        db.commit()
        return deleted_count
