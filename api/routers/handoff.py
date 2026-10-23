"""Handoff read/history/delete endpoints (T19). Reads never touch the advisor."""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import get_current_user, require_admin
from api.database import get_db
from api.handoff_service import ensure_handoff
from api.models_api import (
    HandoffHistoryItem,
    HandoffHistoryOut,
    HandoffOut,
    HandoffRevisionListOut,
    HandoffRevisionOut,
)
from api.models_db import Project, Upload, User
from api.routers.share import _active_share_or_404
from api.routers.upload import _require_upload_access

router = APIRouter(tags=["handoff"])


def _loads(raw: Optional[str], default: Any) -> Any:
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _change_log(upload: Upload) -> List[HandoffRevisionOut]:
    out = []
    for e in _loads(upload.handoff_revisions, []):
        if not isinstance(e, dict):
            continue
        out.append(HandoffRevisionOut(
            revision=e.get("revision") or 0,
            created_at=e.get("created_at") or upload.created_at,
            # Stored actor may be a user email; never expose it (mentors read this log).
            actor=e.get("actor") if e.get("actor") in ("user", "advisor", "system") else ("system" if e.get("kind") == "created" else "user"),
            kind=e.get("kind") if e.get("kind") in ("created", "apply", "undo", "revise", "keep_from_previous") else "apply",
            group_id=e.get("group_id"),
            summary=e.get("summary") or "",
            rows_affected=e.get("rows_affected") or {},
        ))
    return out


def _handoff_out(upload: Upload, read_only: bool, with_steps: bool = True) -> HandoffOut:
    return HandoffOut(
        upload_id=upload.id,
        project_id=upload.project_id,
        status=upload.handoff_status,
        revision=upload.handoff_revision or 0,
        markdown=upload.handoff_md,
        steps=_loads(upload.handoff_steps, []) if with_steps else [],
        change_log=_change_log(upload),
        updated_at=upload.handoff_updated_at,
        read_only=read_only,
    )


@router.get("/upload/{upload_id}/handoff", response_model=HandoffOut)
def get_handoff(upload_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    if upload.handoff_status == "none" and upload.status == "active":
        ensure_handoff(db, db.get(Project, upload.project_id), upload)
    # replaced and deleted handoffs are history: open them read-only
    return _handoff_out(upload, read_only=upload.handoff_status in ("replaced", "deleted"))


@router.get("/upload/{upload_id}/handoff/revisions", response_model=HandoffRevisionListOut)
def get_handoff_revisions(upload_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    return HandoffRevisionListOut(upload_id=upload.id, revisions=_change_log(upload))


@router.get("/share/{token}/handoff", response_model=HandoffOut)
def mentor_handoff(token: str, db: Session = Depends(get_db)):
    """Read-only for mentors. Authorized by an active share token only; current handoff, no steps."""
    share = _active_share_or_404(token, db)
    upload = (
        db.query(Upload)
        .filter(Upload.project_id == share.project_id, Upload.status == "active", Upload.handoff_status == "current")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Handoff not found")
    out = _handoff_out(upload, read_only=True, with_steps=False)
    # The document's change log prints the acting resident's email; mentors do not get it.
    if out.markdown:
        out.markdown = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "resident", out.markdown)
    return out


@router.get("/projects/{project_id}/handoff-history", response_model=HandoffHistoryOut)
def handoff_history(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if user.role != "admin" and project.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Project access denied")
    rows = db.query(Upload).filter(
        Upload.project_id == project_id, Upload.handoff_status.in_(("replaced", "deleted"))
    ).all()
    rows.sort(key=lambda u: (u.handoff_replaced_at or u.created_at, u.id), reverse=True)
    return HandoffHistoryOut(project_id=project_id, items=[
        HandoffHistoryItem(
            upload_id=u.id, file_name=u.original_filename or u.filename or "", created_at=u.created_at,
            replaced_at=u.handoff_replaced_at, status=u.handoff_status, revision=u.handoff_revision or 0,
            change_log_entries=len(_change_log(u)),
        ) for u in rows
    ])


@router.delete("/upload/{upload_id}/handoff")
def delete_handoff(upload_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    if upload.handoff_status != "replaced":
        code = "handoff_is_current" if upload.handoff_status in ("current", "pending_choice") else "handoff_not_replaced"
        raise HTTPException(status_code=409, detail={"code": code, "message": "Only a replaced handoff can be deleted."})
    upload.handoff_md = None
    upload.handoff_steps = "[]"
    upload.handoff_revisions = json.dumps([
        {k: v for k, v in e.items() if k != "steps_snapshot"} for e in _loads(upload.handoff_revisions, []) if isinstance(e, dict)
    ])
    upload.handoff_status = "deleted"
    db.commit()
    log_action(db, upload.project_id, "handoff_deleted", {"upload_id": upload.id, "user_id": user.id})
    return {"ok": True}


@router.delete("/admin/upload/{upload_id}/handoff-log")
def admin_purge_change_log(upload_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin-only: drop the change log of a deleted handoff. Never touches current or replaced ones."""
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    if upload.handoff_status != "deleted":
        raise HTTPException(status_code=409, detail={"code": "handoff_not_deleted", "message": "Only the log of a deleted handoff can be purged."})
    upload.handoff_revisions = "[]"
    db.commit()
    log_action(db, upload.project_id, "handoff_log_purged", {"upload_id": upload.id, "user_id": admin.id})
    return {"ok": True}
