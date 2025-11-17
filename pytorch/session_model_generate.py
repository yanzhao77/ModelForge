"""
支持会话和记忆的模型生成器
继承自原有的 model_generate，增加数据库集成
"""
import os
import sys
from typing import Optional, List, Dict

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytorch.model_generate import model_generate
from database.db_manager import DatabaseManager
from api.session_service import SessionService
from api.memory_service import MemoryService


class SessionModelGenerate(model_generate):
    """
    支持会话管理和记忆系统的模型生成器
    """
    
    def __init__(
        self,
        user_id: int,
        session_id: int = None,
        db_manager: DatabaseManager = None,
        **kwargs
    ):
        """
        初始化会话模型生成器
        
        Args:
            user_id: 用户ID
            session_id: 会话ID（如果为None，则创建新会话）
            db_manager: 数据库管理器
            **kwargs: 传递给父类的其他参数
        """
        super().__init__(**kwargs)
        
        self.user_id = user_id
        self.db_manager = db_manager or DatabaseManager()
        
        # 初始化或加载会话
        with self.db_manager.get_session() as db:
            if session_id:
                self.session_id = session_id
                # 加载历史消息
                self._load_session_history(db)
            else:
                # 创建新会话
                session = SessionService.create_session(
                    db=db,
                    user_id=user_id,
                    title="新对话",
                    model_path=self.model_path
                )
                self.session_id = session.id
    
    def _load_session_history(self, db):
        """从数据库加载会话历史"""
        messages = SessionService.get_session_history(db, self.session_id)
        self.message_dict = messages
        print(f"已加载 {len(messages)} 条历史消息")
    
    def _save_message(self, role: str, content: str):
        """保存消息到数据库"""
        with self.db_manager.get_session() as db:
            SessionService.add_message(
                db=db,
                session_id=self.session_id,
                role=role,
                content=content,
                token_count=len(content)  # 简单估算
            )
    
    def _extract_and_save_memories(self, user_message: str):
        """从用户消息中提取并保存记忆"""
        with self.db_manager.get_session() as db:
            memories = MemoryService.extract_memories_from_message(
                db=db,
                user_id=self.user_id,
                message_content=user_message,
                session_id=self.session_id
            )
            if memories:
                print(f"提取了 {len(memories)} 条记忆")
    
    def _get_relevant_memories(self, query: str) -> str:
        """获取相关记忆并格式化为上下文"""
        with self.db_manager.get_session() as db:
            memories = MemoryService.get_relevant_memories_for_query(
                db=db,
                user_id=self.user_id,
                query=query,
                limit=3
            )
            return MemoryService.format_memories_for_context(memories)
    
    def pipeline_answer(self, question: str) -> str:
        """
        重写 pipeline_answer，增加会话和记忆支持
        """
        if question.lower() == 'exit':
            print("退出对话")
            self.release_resources()
            self.is_running = False
            return "对话已结束"
        
        # 提取并保存记忆
        self._extract_and_save_memories(question)
        
        # 获取相关记忆
        memory_context = self._get_relevant_memories(question)
        
        # 如果有记忆，添加到问题前
        if memory_context:
            question_with_memory = f"{memory_context}\n\n{question}"
        else:
            question_with_memory = question
        
        # 调用父类方法生成回答
        response = super().pipeline_answer(question_with_memory)
        
        # 保存用户消息和助手回复
        self._save_message("user", question)
        self._save_message("assistant", response)
        
        # 自动生成会话标题（如果是第一条消息）
        with self.db_manager.get_session() as db:
            message_count = SessionService.get_session_message_count(db, self.session_id)
            if message_count == 2:  # 第一轮对话（用户+助手）
                SessionService.auto_generate_title(db, self.session_id)
        
        return response
    
    def get_session_info(self) -> Dict:
        """获取当前会话信息"""
        with self.db_manager.get_session() as db:
            session = SessionService.get_session_by_id(db, self.session_id)
            if session:
                return {
                    "session_id": session.id,
                    "title": session.title,
                    "created_at": session.created_at.isoformat(),
                    "message_count": SessionService.get_session_message_count(db, self.session_id)
                }
        return {}
    
    def clear_session(self):
        """清空当前会话"""
        with self.db_manager.get_session() as db:
            SessionService.clear_session_messages(db, self.session_id, self.user_id)
        self.message_dict = []
        print("会话已清空")
    
    def switch_session(self, new_session_id: int):
        """切换到另一个会话"""
        with self.db_manager.get_session() as db:
            session = SessionService.get_session_by_id(db, new_session_id, self.user_id)
            if not session:
                print(f"会话 {new_session_id} 不存在或无权访问")
                return False
            
            self.session_id = new_session_id
            self._load_session_history(db)
            print(f"已切换到会话: {session.title}")
            return True
    
    def list_user_sessions(self) -> List[Dict]:
        """列出用户的所有会话"""
        with self.db_manager.get_session() as db:
            sessions = SessionService.get_user_sessions(db, self.user_id)
            return [
                {
                    "id": s.id,
                    "title": s.title,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                    "message_count": SessionService.get_session_message_count(db, s.id)
                }
                for s in sessions
            ]
