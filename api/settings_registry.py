from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.config import settings
from api.models_api import SettingOut
from api.models_db import AppSetting


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: str
    secret: bool
    runtime: bool
    default: Callable[[], str]


REGISTRY: dict[str, SettingSpec] = {
    "clinic_name": SettingSpec("clinic_name", "string", False, True, lambda: "Rutgers IM Clinic"),
    "ai_provider": SettingSpec("ai_provider", "string", False, True, lambda: settings.ai_provider),
    "openrouter_model": SettingSpec("openrouter_model", "string", False, True, lambda: settings.openrouter_model),
    "openai_model": SettingSpec("openai_model", "string", False, True, lambda: settings.openai_model),
    "local_model": SettingSpec("local_model", "string", False, True, lambda: settings.local_model),
    "local_api_base": SettingSpec("local_api_base", "string", False, True, lambda: settings.local_api_base),
    "ai_rate_limit_per_hour": SettingSpec("ai_rate_limit_per_hour", "integer", False, True, lambda: "20"),
    "cors_origins": SettingSpec("cors_origins", "string", False, True, lambda: "http://localhost:5173"),
}

REJECTED_DB_KEYS = {
    "openrouter_api_key",
    "openai_api_key",
    "local_api_key",
    "smtp_pass",
    "secret_key",
    "fernet_key",
    "db_url",
    "database_url",
}


def _validate_value(spec: SettingSpec, value: str) -> str:
    if spec.type == "integer":
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{spec.key} must be an integer")
        return str(parsed)
    if spec.key == "ai_provider":
        normalized = value.strip().lower()
        if normalized not in ("openrouter", "openai", "local", "stub"):
            raise HTTPException(status_code=400, detail="ai_provider must be one of: openrouter, openai, local, stub")
        if normalized == "stub" and settings.environment == "production":
            raise HTTPException(status_code=400, detail="ai_provider 'stub' is test-only and cannot be enabled when environment=production")
        return normalized
    if spec.key == "cors_origins":
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="cors_origins must be comma-separated or a JSON list")
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise HTTPException(status_code=400, detail="cors_origins JSON value must be a list of strings")
        return value
    return str(value)


def require_allowed_setting(key: str) -> SettingSpec:
    normalized = key.strip().lower()
    if normalized in REJECTED_DB_KEYS:
        raise HTTPException(status_code=400, detail=f"{key} is secret or boot-time configuration and cannot be changed at runtime")
    spec = REGISTRY.get(normalized)
    if not spec:
        raise HTTPException(status_code=400, detail=f"Unsupported setting key: {key}")
    return spec


def list_runtime_settings(db: Session) -> list[SettingOut]:
    rows = {row.key: row.value for row in db.query(AppSetting).all()}
    result: list[SettingOut] = []
    for key, spec in REGISTRY.items():
        if spec.secret:
            continue
        value = rows.get(key, spec.default())
        result.append(SettingOut(key=key, value=value, type=spec.type, secret=spec.secret, runtime=spec.runtime))
    return result


def set_runtime_setting(db: Session, key: str, value: str) -> SettingOut:
    spec = require_allowed_setting(key)
    clean = _validate_value(spec, value)
    row = db.query(AppSetting).filter_by(key=spec.key).first()
    if row:
        row.value = clean
    else:
        db.add(AppSetting(key=spec.key, value=clean))
    db.commit()
    return SettingOut(key=spec.key, value=clean, type=spec.type, secret=spec.secret, runtime=spec.runtime)


def get_runtime_setting(db: Session, key: str):
    spec = REGISTRY.get(key)
    if not spec or not spec.runtime:
        return None
    row = db.query(AppSetting).filter_by(key=key).first()
    value = row.value if row else spec.default()
    try:
        value = _validate_value(spec, value)
    except HTTPException:
        value = _validate_value(spec, spec.default())
    if spec.type == "integer":
        return int(value)
    return value
