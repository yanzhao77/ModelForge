"""Security utilities: password hashing, JWT tokens, auth dependencies."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.database import get_db
from models.records import User

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 password hashing (compatible with legacy auth)."""
    import hashlib
    import secrets
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    )
    return salt + "$" + pwd_hash.hex()


def verify_password(password: str, password_hash: str) -> bool:
    import hashlib
    try:
        salt, pwd_hash = password_hash.split("$")
        new_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
        )
        return new_hash.hex() == pwd_hash
    except Exception:
        return False


def create_access_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def _current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: DBSession = Depends(get_db),
) -> Optional[User]:
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None:
        return None
    try:
        user_id = int(payload.get("sub", "0"))
    except (TypeError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id).first()


def get_current_user(user: Optional[User] = Depends(_current_user)) -> User:
    """Require a valid logged-in user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_optional(user: Optional[User] = Depends(_current_user)) -> Optional[User]:
    """Auth optional: returns user or None."""
    return user