"""Auth API routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session as DBSession

from core.database import get_db
from core.security import get_current_user
from models.records import User
from services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


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
    return {"message": message, "user": user.to_dict()}


@router.post("/login")
def login(req: LoginRequest, db: DBSession = Depends(get_db)):
    ok, message, user, token = AuthService.login(db, req.username, req.password)
    if not ok:
        raise HTTPException(status_code=401, detail=message)
    return {"message": message, "token": token, "user": user.to_dict()}


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