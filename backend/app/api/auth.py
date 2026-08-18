"""Auth API routes."""
from typing import Optional
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.database import get_db
from core.security import get_current_user
from models.records import User
from services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_browser_session(response: Response, token: str) -> str:
    """Store browser credentials in HttpOnly cookies and return only a CSRF nonce."""
    csrf_token = secrets.token_urlsafe(32)
    max_age = settings.jwt_expire_minutes * 60
    response.set_cookie(
        settings.session_cookie_name, token, max_age=max_age,
        secure=settings.session_cookie_secure, httponly=True,
        samesite=settings.session_cookie_samesite, path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name, csrf_token, max_age=max_age,
        secure=settings.session_cookie_secure, httponly=False,
        samesite=settings.session_cookie_samesite, path="/",
    )
    return csrf_token


def _clear_browser_session(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/register")
def register(req: RegisterRequest, db: DBSession = Depends(get_db)):
    ok, message, user = AuthService.register(db, req.username, req.password, req.email)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    # Registration creates an account only. Browser sessions are established by
    # the explicit Cookie-mode login endpoint, so API test clients and bearer
    # integrations never inherit an ambient authenticated session by accident.
    return {"message": message, "user": user.to_dict()}


@router.post("/login")
def login(req: LoginRequest, response: Response, request: Request, db: DBSession = Depends(get_db)):
    ok, message, user, token = AuthService.login(db, req.username, req.password)
    if not ok:
        raise HTTPException(status_code=401, detail=message)
    cookie_transport = request.headers.get("X-Auth-Transport", "bearer").lower() == "cookie"
    if cookie_transport:
        csrf_token = _set_browser_session(response, token)
        # Cookie-mode browser clients never receive the JWT in the response body.
        return {"message": message, "user": user.to_dict(), "csrf_token": csrf_token}
    # Explicit bearer/API clients remain stateless and receive no Set-Cookie.
    return {"message": message, "user": user.to_dict(), "token": token}


@router.post("/logout")
def logout(response: Response):
    _clear_browser_session(response)
    return {"message": "Logged out"}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    ok, message = AuthService.change_password(db, user, req.old_password, req.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}
