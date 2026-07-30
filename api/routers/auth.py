from threading import Lock

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from api.auth import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    create_user_session,
    get_current_user,
    get_session_from_request,
    hash_password,
    set_session_cookie,
    verify_password,
)
from api.database import get_db
from api.models_api import AuthCredentials, UserOut
from api.models_db import User

router = APIRouter(prefix="/auth", tags=["auth"])

_bootstrap_lock = Lock()



def _normal_email(email: str) -> str:
    return email.strip().lower()


@router.post("/register", response_model=UserOut)
def register(body: AuthCredentials, response: Response, db: Session = Depends(get_db)):
    email = _normal_email(body.email)
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    with _bootstrap_lock:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")
        role = "admin" if db.query(User).count() == 0 else "resident"
        user = User(email=email, password_hash=hash_password(body.password), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
    _, token = create_user_session(db, user)
    set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserOut)
def login(body: AuthCredentials, response: Response, db: Session = Depends(get_db)):
    email = _normal_email(body.email)
    user = db.query(User).filter(User.email == email).first()
    if not user or user.disabled_at is not None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _, token = create_user_session(db, user)
    set_session_cookie(response, token)
    return user


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session = get_session_from_request(db, request)
    if session:
        session.revoked_at = datetime.utcnow()
        db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
