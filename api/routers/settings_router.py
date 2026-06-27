from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from api.database import get_db
from api.models_db import AppSetting

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingPayload(BaseModel):
    key: str
    value: str


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    rows = db.query(AppSetting).all()
    return {r.key: r.value for r in rows}


@router.put("")
def upsert_setting(payload: SettingPayload, db: Session = Depends(get_db)):
    row = db.query(AppSetting).filter_by(key=payload.key).first()
    if row:
        row.value = payload.value
    else:
        db.add(AppSetting(key=payload.key, value=payload.value))
    db.commit()
    return {"key": payload.key, "value": payload.value}
