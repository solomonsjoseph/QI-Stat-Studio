from __future__ import annotations

import base64
import hashlib
import hmac
import time
import secrets
from datetime import datetime, timedelta
from typing import Optional

try:
    from itsdangerous import BadSignature, BadTimeSignature, URLSafeTimedSerializer
except ModuleNotFoundError:  # pragma: no cover - test environment fallback
    BadSignature = BadTimeSignature = URLSafeTimedSerializer = None
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.config import settings
from api.database import get_db
from api.models_db import Project, User, UserSession

SESSION_COOKIE_NAME = "qiss_session"
SESSION_SECONDS = 8 * 60 * 60
_PASSWORD_ITERATIONS = 260_000


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session_signer():
    if URLSafeTimedSerializer is None:
        return None
    return URLSafeTimedSerializer(settings.secret_key, salt="qiss-session")


def _fallback_signature(token: str, issued_at: str) -> str:
    payload = f"{token}.{issued_at}".encode("utf-8")
    return hmac.new(settings.secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _sign_session_token(token: str) -> str:
    signer = _session_signer()
    if signer is not None:
        return signer.dumps(token)
    issued_at = str(int(time.time()))
    return f"{token}.{issued_at}.{_fallback_signature(token, issued_at)}"


def _unsign_session_cookie(cookie_value: str) -> str | None:
    signer = _session_signer()
    if signer is not None:
        try:
            return signer.loads(cookie_value, max_age=SESSION_SECONDS)
        except (BadSignature, BadTimeSignature):
            return None
    try:
        token, issued_at, signature = cookie_value.rsplit(".", 2)
        if int(time.time()) - int(issued_at) > SESSION_SECONDS:
            return None
    except (TypeError, ValueError):
        return None
    expected = _fallback_signature(token, issued_at)
    return token if hmac.compare_digest(signature, expected) else None

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_s, salt_s, digest_s = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = base64.urlsafe_b64decode(salt_s.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_s.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(actual, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def create_user_session(db: Session, user: User) -> tuple[UserSession, str]:
    token = new_session_token()
    now = datetime.utcnow()
    session = UserSession(
        user_id=user.id,
        token_hash=_hash_token(token),
        created_at=now,
        expires_at=now + timedelta(seconds=SESSION_SECONDS),
        last_seen_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, token


def get_session_from_request(db: Session, request: Request) -> Optional[UserSession]:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        return None
    token = _unsign_session_cookie(cookie_value)
    if not token:
        return None
    session = db.query(UserSession).filter(UserSession.token_hash == _hash_token(token)).first()
    now = datetime.utcnow()
    if not session or session.revoked_at is not None or session.expires_at <= now:
        return None
    session.last_seen_at = now
    db.commit()
    db.refresh(session)
    return session


def get_current_user(db: Session = Depends(get_db), request: Request = None) -> User:
    session = get_session_from_request(db, request)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = db.get(User, session.user_id)
    if not user or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_project_owner(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if user.role == "admin":
        return project
    if project.owner_user_id is not None and project.owner_user_id == user.id:
        return project
    raise HTTPException(status_code=403, detail="Project access denied")


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=_sign_session_token(token),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, httponly=True, secure=settings.cookie_secure, samesite="lax")
