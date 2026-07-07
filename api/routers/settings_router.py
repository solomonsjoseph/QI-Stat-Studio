from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import require_admin
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
