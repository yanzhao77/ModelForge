"""
数据库管理器
提供数据库连接、初始化和基础操作
"""
import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from models.database_models import Base, User, Session, Message, Memory, ModelConfig


class DatabaseManager:
    """数据库管理器单例"""
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls, db_path=None):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path=None):
        if self._initialized:
            return
        
        if db_path is None:
            # 默认数据库路径
            db_dir = os.path.join(os.path.expanduser("~"), ".modelforge")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "modelforge.db")
        
        self.db_path = db_path
        self._engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,  # 设置为 True 可以看到 SQL 语句
            pool_pre_ping=True,
            connect_args={'check_same_thread': False}  # SQLite 特定配置
        )
        
        self._session_factory = sessionmaker(bind=self._engine)
        self.Session = scoped_session(self._session_factory)
        
        # 创建所有表
        self.init_db()
        self._initialized = True
    
    def init_db(self):
        """初始化数据库，创建所有表"""
        Base.metadata.create_all(self._engine)
        print(f"数据库初始化完成: {self.db_path}")
    
    def drop_all(self):
        """删除所有表（谨慎使用）"""
        Base.metadata.drop_all(self._engine)
        print("所有表已删除")
    
    @contextmanager
    def get_session(self):
        """获取数据库会话的上下文管理器"""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def create_session(self):
        """创建一个新的数据库会话"""
        return self.Session()
    
    def close(self):
        """关闭数据库连接"""
        if self._engine:
            self._engine.dispose()
            print("数据库连接已关闭")


# 全局数据库管理器实例
db_manager = DatabaseManager()


def get_db():
    """依赖注入函数，用于 FastAPI"""
    session = db_manager.create_session()
    try:
        yield session
    finally:
        session.close()
