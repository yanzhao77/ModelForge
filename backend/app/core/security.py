"""Security utilities: password hashing, JWT tokens, auth dependencies."""
from datetime import datetime, timedelta, timezone

import jwt
from core.api_contracts import correlation_id, problem
from core.config import settings
from core.database import get_db
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from models.records import User
from sqlalchemy.orm import Session as DBSession

ALGORITHM = "HS256"
PBKDF2_SHA256_ITERATIONS = 600_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Create a versioned PBKDF2-SHA256 password hash using a modern work factor."""
    import hashlib
    import secrets

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_SHA256_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_SHA256_ITERATIONS}${salt}${digest.hex()}"


def _password_hash_parameters(password_hash: str) -> tuple[int, str, str] | None:
    """Parse versioned hashes and the historical ``salt$digest`` format."""
    parts = password_hash.split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        try:
            return int(parts[1]), parts[2], parts[3]
        except ValueError:
            return None
    if len(parts) == 2:
        return 100_000, parts[0], parts[1]
    return None


def verify_password(password: str, password_hash: str) -> bool:
    """Verify legacy and versioned hashes without timing-dependent comparison."""
    import hashlib
    import hmac

    parameters = _password_hash_parameters(password_hash)
    if parameters is None:
        return False
    iterations, salt, expected = parameters
    if iterations < 100_000 or iterations > 2_000_000:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()
    return hmac.compare_digest(derived, expected)


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether a successfully verified hash should be upgraded at login."""
    parameters = _password_hash_parameters(password_hash)
    return parameters is None or parameters[0] < PBKDF2_SHA256_ITERATIONS


def create_access_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def _current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: DBSession = Depends(get_db),
) -> User | None:
    # Bearer remains supported for programmatic clients. Browser sessions use an
    # HttpOnly cookie so JavaScript never receives the access token.
    token = credentials.credentials if credentials is not None else request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    try:
        user_id = int(payload.get("sub", "0"))
    except (TypeError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id).first()


def get_current_user(user: User | None = Depends(_current_user)) -> User:
    """Require a valid logged-in user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    return user


def get_current_user_optional(user: User | None = Depends(_current_user)) -> User | None:
    """Auth optional: returns user or None."""
    return user


def get_runtime_admin(user: User = Depends(get_current_user)) -> User:
    """Require an explicitly configured administrator for shared runtime state."""
    admins = {name.strip() for name in settings.runtime_admin_usernames.split(",") if name.strip()}
    if user.username not in admins:
        raise problem(
            status.HTTP_403_FORBIDDEN,
            "RUNTIME_ADMIN_REQUIRED",
            "Runtime administrator privileges are required.",
            correlation=correlation_id(),
        )
    return user
