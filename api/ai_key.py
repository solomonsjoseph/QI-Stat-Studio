"""App-wide AI provider key: Fernet-encrypted row in app_settings, overriding the env key."""
from __future__ import annotations

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.config import settings
from api.models_db import AppSetting

KEYED_PROVIDERS = ("openrouter", "openai", "gemini", "local")


def _row_key(provider: str) -> str:
    return f"ai_key_enc:{provider}"


_PLACEHOLDERS = {"changeme", "change-me", "your-key-here", "your_key_here", "your-api-key", "xxx"}


def env_key(provider: str) -> str | None:
    if provider not in KEYED_PROVIDERS:
        return None
    key = (getattr(settings, f"{provider}_api_key", "") or "").strip()
    if not key or key.endswith("...") or key.lower() in _PLACEHOLDERS:
        return None
    return key


def stored_key(db: Session, provider: str) -> str | None:
    row = db.query(AppSetting).filter_by(key=_row_key(provider)).first()
    if not row or not row.value:
        return None
    try:
        return settings.fernet.decrypt(row.value.encode()).decode() or None
    except InvalidToken:
        return None


def save_key(db: Session, provider: str, key: str) -> None:
    token = settings.fernet.encrypt(key.encode()).decode()
    row = db.query(AppSetting).filter_by(key=_row_key(provider)).first()
    if row:
        row.value = token
    else:
        db.add(AppSetting(key=_row_key(provider), value=token))
    db.commit()


def clear_key(db: Session, provider: str) -> None:
    db.query(AppSetting).filter_by(key=_row_key(provider)).delete()
    db.commit()


def resolve_key(db: Session, provider: str) -> tuple[str | None, str]:
    """Return (key, source) where source is settings, env, or none. Settings wins over env."""
    saved = stored_key(db, provider)
    if saved:
        return saved, "settings"
    env = env_key(provider)
    return (env, "env") if env else (None, "none")


def advisor_unavailable(db: Session, provider: str) -> HTTPException:
    """Shared 503 for AI endpoints that need a key. Never includes the key."""
    _, source = resolve_key(db, provider)
    return HTTPException(
        status_code=503,
        detail={
            "code": "advisor_unavailable",
            "message": "The QI Stat Advisor is not available because no API key is set. Add a key in Settings, or continue without the QI Stat Advisor.",
            "key_source": source,
        },
    )


_BUSY_ERRORS = {"RateLimitError", "Timeout", "APITimeoutError", "APIConnectionError", "ServiceUnavailableError", "InternalServerError"}


def advisor_failed(exc: BaseException | None) -> HTTPException:
    """Resident-safe error for a provider call that raised. Only the exception class is used to pick
    the sentence; the provider's own text can carry request content and is never returned."""
    busy = exc is not None and any(c.__name__ in _BUSY_ERRORS for c in type(exc).__mro__)
    if busy:
        return HTTPException(status_code=503, detail={
            "code": "advisor_busy",
            "message": "The QI Stat Advisor is busy right now. Wait a minute and try again, or continue without it.",
        })
    return HTTPException(status_code=502, detail={
        "code": "advisor_error",
        "message": "The QI Stat Advisor could not answer. Try again, or continue without it.",
    })
