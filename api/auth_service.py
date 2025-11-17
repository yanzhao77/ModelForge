"""
用户认证服务
提供用户注册、登录、JWT token 生成和验证
"""
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
import jwt
from models.database_models import User


class AuthService:
    """用户认证服务"""
    
    # JWT 配置
    SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7天
    
    @staticmethod
    def hash_password(password: str) -> str:
        """密码哈希"""
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return f"{salt}${pwd_hash.hex()}"
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """验证密码"""
        try:
            salt, pwd_hash = password_hash.split('$')
            new_hash = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                100000
            )
            return new_hash.hex() == pwd_hash
        except Exception:
            return False
    
    @classmethod
    def create_access_token(cls, user_id: int, username: str) -> str:
        """创建 JWT token"""
        expire = datetime.utcnow() + timedelta(minutes=cls.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "user_id": user_id,
            "username": username,
            "exp": expire,
            "iat": datetime.utcnow()
        }
        token = jwt.encode(payload, cls.SECRET_KEY, algorithm=cls.ALGORITHM)
        return token
    
    @classmethod
    def verify_token(cls, token: str) -> Optional[dict]:
        """验证 JWT token"""
        try:
            payload = jwt.decode(token, cls.SECRET_KEY, algorithms=[cls.ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    @staticmethod
    def register_user(session, username: str, password: str, email: str = None) -> tuple[bool, str, Optional[User]]:
        """
        注册新用户
        返回: (成功标志, 消息, 用户对象)
        """
        # 检查用户名是否已存在
        existing_user = session.query(User).filter(User.username == username).first()
        if existing_user:
            return False, "用户名已存在", None
        
        # 检查邮箱是否已存在
        if email:
            existing_email = session.query(User).filter(User.email == email).first()
            if existing_email:
                return False, "邮箱已被注册", None
        
        # 创建新用户
        password_hash = AuthService.hash_password(password)
        new_user = User(
            username=username,
            password_hash=password_hash,
            email=email,
            created_at=datetime.utcnow(),
            last_login=datetime.utcnow()
        )
        
        try:
            session.add(new_user)
            session.commit()
            session.refresh(new_user)
            return True, "注册成功", new_user
        except Exception as e:
            session.rollback()
            return False, f"注册失败: {str(e)}", None
    
    @staticmethod
    def login_user(session, username: str, password: str) -> tuple[bool, str, Optional[User], Optional[str]]:
        """
        用户登录
        返回: (成功标志, 消息, 用户对象, token)
        """
        # 查找用户
        user = session.query(User).filter(User.username == username).first()
        if not user:
            return False, "用户名或密码错误", None, None
        
        # 验证密码
        if not AuthService.verify_password(password, user.password_hash):
            return False, "用户名或密码错误", None, None
        
        # 检查用户是否激活
        if not user.is_active:
            return False, "账户已被禁用", None, None
        
        # 更新最后登录时间
        user.last_login = datetime.utcnow()
        session.commit()
        
        # 生成 token
        token = AuthService.create_access_token(user.id, user.username)
        
        return True, "登录成功", user, token
    
    @staticmethod
    def get_user_by_id(session, user_id: int) -> Optional[User]:
        """根据 ID 获取用户"""
        return session.query(User).filter(User.id == user_id).first()
    
    @staticmethod
    def get_user_by_username(session, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        return session.query(User).filter(User.username == username).first()
