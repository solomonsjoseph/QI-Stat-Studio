from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from api.models_db import AuditLog

_BLOCKED_META_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "raw",
    "prompt",
    "content",
    "email",
    "name",
    "text",
    "url",
    "title",
    "description",
    "deadline",
)


def _is_blocked_key(key: Any) -> bool:
    key_l = str(key).lower()
    return any(blocked in key_l for blocked in _BLOCKED_META_KEY_PARTS)


def sanitize_audit_metadata(meta: Any) -> Any:
    if isinstance(meta, dict):
        safe: dict[str, Any] = {}
        redacted_fields: list[str] = []
        for key, value in meta.items():
            key_s = str(key)
            if _is_blocked_key(key_s):
                redacted_fields.append(key_s)
                continue
            sanitized = sanitize_audit_metadata(value)
            if sanitized in ({}, [], None):
                if value not in ({}, [], None):
                    continue
            safe[key_s] = sanitized
        if redacted_fields:
            existing = safe.get("fields")
            if isinstance(existing, list):
                safe["fields"] = sorted({*map(str, existing), *redacted_fields})
            else:
                safe["fields"] = sorted(set(redacted_fields))
        return safe
    if isinstance(meta, list):
        safe_items = [sanitize_audit_metadata(item) for item in meta]
        return [item for item in safe_items if item not in ({}, [], None)]
    if isinstance(meta, (str, int, float, bool)) or meta is None:
        return meta
    return str(meta)

SAFE_DIAGNOSTIC_MESSAGES = {
    "internal_error": "Unexpected server error",
    "analysis_failed": "Analysis failed",
    "notification_failed": "Notification delivery failed",
    "ai_service_unavailable": "AI service unavailable",
}


def safe_diagnostic_message(kind: str) -> str:
    return SAFE_DIAGNOSTIC_MESSAGES.get(kind, SAFE_DIAGNOSTIC_MESSAGES["internal_error"])


def safe_notification_error() -> str:
    return safe_diagnostic_message("notification_failed")



def _safe_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = sanitize_audit_metadata(meta or {})
    return sanitized if isinstance(sanitized, dict) else {}


def log_action(db: Session, project_id: int | None, action: str, meta: dict[str, Any] | None = None, request_id: str | None = None) -> AuditLog:
    payload = _safe_meta(meta)
    if request_id:
        payload["request_id"] = request_id
    row = AuditLog(project_id=project_id, action=action, metadata_json=json.dumps(payload))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
