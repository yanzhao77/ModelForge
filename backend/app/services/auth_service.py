"""Authentication service: register / login / password management."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from core.security import create_access_token, hash_password, verify_password
from models.records import User


class AuthService:
    """User registration and login (DB-backed)."""

    @staticmethod
    def register(
        db: DBSession, username: str, password: str, email: Optional[str] = None
    ) -> tuple:
        """Register a new user. Returns (ok, message, user)."""
        username = (username or "").strip()
        if len(username) < 3 or len(username) > 32:
            return False, "用户名长度须在 3-32 个字符之间", None
        if not password or len(password) < 6:
            return False, "密码至少 6 位", None

        if db.query(User).filter(User.username == username).first():
            return False, "用户名已存在", None
        if email:
            if db.query(User).filter(User.email == email).first():
                return False, "邮箱已被注册", None

        user = User(
            username=username,
            password_hash=hash_password(password),
            email=email or None,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return True, "注册成功", user

    @staticmethod
    def login(db: DBSession, username: str, password: str) -> tuple:
        """Login. Returns (ok, message, user, token)."""
        user = db.query(User).filter(User.username == (username or "").strip()).first()
        if not user or not verify_password(password or "", user.password_hash):
            return False, "用户名或密码错误", None, None
        if not user.is_active:
            return False, "账号已被禁用", None, None
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        token = create_access_token(user.id, user.username)
        return True, "登录成功", user, token

    @staticmethod
    def change_password(
        db: DBSession, user: User, old_password: str, new_password: str
    ) -> tuple:
        """Change password. Returns (ok, message)."""
        if not verify_password(old_password or "", user.password_hash):
            return False, "原密码错误"
        if not new_password or len(new_password) < 6:
            return False, "新密码至少 6 位"
        user.password_hash = hash_password(new_password)
        db.commit()
        return True, "密码已更新"