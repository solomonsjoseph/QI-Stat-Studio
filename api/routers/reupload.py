"""Keep-or-fresh choice after re-uploading an identical file and dictionary."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import get_current_user
from api.cleaning_runtime import StepsApplyError, rebuild_profile
from api.database import get_db
from api.handoff import new_revision_entry
from api.models_api import ReuploadFollowUpIn, ReuploadFollowUpOut
from api.models_db import Project, Upload, User, WarningGroup
from api.routers.handoff import _handoff_out
from api.routers.upload import _require_upload_access
from api.staleness import check_and_apply_inputs_fingerprint, compute_inputs_fingerprint

router = APIRouter(prefix="/upload", tags=["reupload"])
_CARRIED = ("handoff_md", "handoff_steps", "acknowledged_flags", "col_types", "column_map", "column_roles")


def _loads(raw: Any, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _keep(db: Session, project: Project, new: Upload, old: Upload) -> None:
    for col in _CARRIED:
        setattr(new, col, getattr(old, col))
    steps = _loads(old.handoff_steps, [])
    rev = (old.handoff_revision or 0) + 1
    entry = new_revision_entry("keep_from_previous", "Kept earlier changes after re-upload of the same file.",
                               steps, steps, [], "user", revision=rev)
    new.handoff_revision = rev
    new.handoff_revisions = json.dumps(_loads(old.handoff_revisions, []) + [entry])
    for g in db.query(WarningGroup).filter(WarningGroup.upload_id == old.id).all():
        g.upload_id = new.id
    # The cached profile was built on raw data; rebuild it from the cleaned frame.
    # StepsApplyError (409) propagates; the caller rolls back so the upload stays pending_choice.
    rebuild_profile(new, db)
    # Same inputs as before: re-baseline the fingerprint so the plan is not marked stale.
    project.inputs_fingerprint = compute_inputs_fingerprint(project, new)


@router.post("/{upload_id}/reupload-choice", response_model=ReuploadFollowUpOut)
def reupload_choice(upload_id: int, body: ReuploadFollowUpIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    new = _require_upload_access(upload_id, db, user)
    if new.handoff_status != "pending_choice" or new.status != "active":
        raise HTTPException(status_code=409, detail={"code": "no_choice_pending", "message": "No re-upload choice is pending."})
    project = db.get(Project, new.project_id)
    old = db.get(Upload, new.handoff_source_upload_id) if new.handoff_source_upload_id else None
    if body.choice == "keep" and old is not None and old.handoff_md:
        try:
            _keep(db, project, new, old)
        except StepsApplyError:
            db.rollback()
            raise
    else:
        if new.handoff_md is None:  # initial build failed at upload time
            from api.handoff_service import ensure_handoff

            new.handoff_status = "none"
            ensure_handoff(db, project, new)
        check_and_apply_inputs_fingerprint(project, new, db)
    new.handoff_status = "current"
    new.handoff_updated_at = datetime.utcnow()
    log_action(db, new.project_id, "reupload_choice", {"upload_id": new.id, "choice": body.choice})
    db.commit()
    db.refresh(new)
    return ReuploadFollowUpOut(upload_id=new.id, choice=body.choice, handoff=_handoff_out(new, read_only=False))
