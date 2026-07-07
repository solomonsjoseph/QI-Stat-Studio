from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import require_admin
from api.config import settings
from api.database import get_db
from api.models_db import FailureLog, User

router = APIRouter(tags=["ops"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)):
    checks: dict[str, bool] = {"database": False, "fernet": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        settings.fernet
        checks["fernet"] = True
    except Exception:
        checks["fernet"] = False
    if all(checks.values()):
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})


def _failure_out(row: FailureLog) -> dict[str, Any]:
    try:
        safe_context = json.loads(row.safe_context_json or "{}")
    except json.JSONDecodeError:
        safe_context = {}
    return {
        "id": row.id,
        "error_type": row.error_type,
        "message": row.message,
        "route": row.route,
        "action": row.action,
        "request_id": row.request_id,
        "project_id": row.project_id,
        "upload_id": row.upload_id,
        "run_id": row.run_id,
        "safe_context": safe_context,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


@router.get("/admin/failures")
def list_failures(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    project_id: Optional[int] = None,
    request_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    query = db.query(FailureLog)
    if project_id is not None:
        query = query.filter(FailureLog.project_id == project_id)
    if request_id:
        query = query.filter(FailureLog.request_id == request_id)
    total = query.count()
    rows = query.order_by(FailureLog.timestamp.desc(), FailureLog.id.desc()).offset(offset).limit(limit).all()
    return {"items": [_failure_out(row) for row in rows], "total": total, "limit": limit, "offset": offset}
