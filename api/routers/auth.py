import hashlib
from threading import Lock

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from api import throttle
from api.audit import log_action
from api.auth import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    create_user_session,
    get_current_user,
    get_session_from_request,
    hash_password,
    needs_rehash,
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


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _email_tag(email: str) -> str:
    """Enough to correlate failures in the audit log without storing the address."""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]


def _too_many(seconds: int) -> HTTPException:
    minutes = max(1, (seconds + 59) // 60)
    return HTTPException(
        status_code=429,
        detail=f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
        headers={"Retry-After": str(seconds)},
    )


# A real hash of a throwaway password, checked when the account does not exist so timing does not reveal it.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/register", response_model=UserOut)
def register(body: AuthCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    wait = throttle.too_many_from(_client_ip(request), "register", throttle.IP_REGISTER_LIMIT, throttle.REGISTER_WINDOW)
    if wait:
        raise _too_many(wait)
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
def login(body: AuthCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    email = _normal_email(body.email)
    wait = throttle.locked_for(email) or throttle.too_many_from(_client_ip(request), "login", throttle.IP_LOGIN_LIMIT, throttle.WINDOW)
    if wait:
        raise _too_many(wait)
    user = db.query(User).filter(User.email == email).first()
    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or user.disabled_at is not None or not password_ok:
        log_action(db, None, "login_failed", {"account": _email_tag(email)})
        if throttle.record_failure(email):
            log_action(db, None, "login_locked", {"account": _email_tag(email)})
        raise HTTPException(status_code=401, detail="Invalid email or password")
    throttle.record_success(email)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
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
