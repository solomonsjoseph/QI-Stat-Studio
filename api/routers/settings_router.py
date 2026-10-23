from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.audit import log_action
from api import ai_key
from api.auth import get_current_user, require_admin
from api.database import get_db
from api.models_api import SettingOut, SettingPayload
from api.models_db import User
from api.settings_registry import list_runtime_settings, set_runtime_setting

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[SettingOut])
def get_settings(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return list_runtime_settings(db)


@router.put("", response_model=SettingOut)
def upsert_setting(payload: SettingPayload, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    setting = set_runtime_setting(db, payload.key, payload.value)
    log_action(db, None, "setting_changed", {"key": setting.key, "type": setting.type, "runtime": setting.runtime})
    return setting


class AIKeyPayload(BaseModel):
    key: str = Field(min_length=8, max_length=512)


class AIKeyStatus(BaseModel):
    configured: bool
    source: str  # settings | env | none
    last4: Optional[str]
    provider: str
    advisor_available: bool


def _ai_key_status(db: Session) -> AIKeyStatus:
    from api.routers.ai import _provider_settings

    provider, key, _, _ = _provider_settings(db)
    _, source = ai_key.resolve_key(db, provider)
    return AIKeyStatus(
        configured=source != "none",
        source=source,
        last4=key[-4:] if key and provider != "stub" else None,
        provider=provider,
        advisor_available=bool(key) or provider in ("local", "stub"),
    )


def _active_keyed_provider(db: Session) -> str:
    from api.routers.ai import _provider_settings

    provider = _provider_settings(db)[0]
    if provider not in ai_key.KEYED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider '{provider}' does not use an API key")
    return provider


# Any signed-in user may manage the app-wide key during the test phase; restrict to require_admin later.
@router.get("/ai-key", response_model=AIKeyStatus)
def get_ai_key_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _ai_key_status(db)


@router.put("/ai-key", response_model=AIKeyStatus)
def put_ai_key(payload: AIKeyPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    provider = _active_keyed_provider(db)
    ai_key.save_key(db, provider, payload.key.strip())
    log_action(db, None, "ai_key_set", {"provider": provider})
    return _ai_key_status(db)


@router.delete("/ai-key", response_model=AIKeyStatus)
def delete_ai_key(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    provider = _active_keyed_provider(db)
    ai_key.clear_key(db, provider)
    log_action(db, None, "ai_key_cleared", {"provider": provider})
    return _ai_key_status(db)
