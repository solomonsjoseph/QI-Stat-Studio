from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import get_current_user
from api.database import get_db
from api.flag_ids import flag_id, with_ids
from api.models_api import (
    FlagStateOut,
    FlagStatesOut,
    GatingOut,
    WarningBatchAcknowledge,
    WarningGroupCreate,
    WarningGroupListOut,
    WarningGroupOut,
)
from api.models_db import Project, Upload, User, WarningGroup
from api.routers.upload import _require_upload_access

_HANDOFF_STATUSES = ("none", "pending_choice", "current", "replaced", "deleted")

router = APIRouter(prefix="/upload", tags=["warning-groups"])


def _loads(raw: Optional[str], default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _err(status: int, code: str, message: str, flag_ids: Optional[List[str]] = None) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message, "field_errors": {"flag_ids": flag_ids or []}},
    )


def _stored_flags(upload: Upload) -> List[Dict[str, Any]]:
    return with_ids(_loads(upload.quality_flags, []))


def _current_errors(upload: Upload) -> Optional[Dict[str, Dict[str, Any]]]:
    """ERROR flags that block now, keyed by id, or None when the check cannot run.

    Re-checks the cleaned data when the upload has stored ERRORs or applied steps, so an ERROR that
    first appears after cleaning (e.g. rows dropped below a minimum) is seen. A stored ERROR whose
    column is gone from the cleaned frame cannot be positively re-checked and stays blocking.
    """
    stored = _stored_flags(upload)
    steps = _loads(upload.handoff_steps, [])
    stored_errors = [f for f in stored if f.get("severity") == "ERROR"]
    if not stored_errors and not steps:
        return {}
    try:
        from api.cleaning_runtime import load_cleaned_dataframe, recheck_flags
        cols = set(map(str, load_cleaned_dataframe(upload).columns)) if steps else None
        firing = {f["id"]: f for f in with_ids(recheck_flags(upload)) if f.get("severity") == "ERROR"}
    except Exception:
        return None  # cannot re-check: ERRORs stay blocking
    if cols is not None:
        for f in stored_errors:
            col = f.get("col")
            if col and col != "(dataset)" and str(col) not in cols:
                firing.setdefault(f["id"], f)
    return firing


def _legacy_acked(upload: Upload, f: Dict[str, Any]) -> bool:
    """WARNING already in Upload.acknowledged_flags: match by id, else rule+col."""
    for a in _loads(upload.acknowledged_flags, []) or []:
        if not isinstance(a, dict):
            continue
        if a.get("id") and f.get("id"):
            if a["id"] == f["id"]:
                return True
        elif a.get("rule") == f.get("rule") and a.get("col") == f.get("col"):
            return True
    return False


def _group_out(g: WarningGroup) -> WarningGroupOut:
    return WarningGroupOut(
        id=g.id, project_id=g.project_id, upload_id=g.upload_id,
        flag_ids=_loads(g.flag_ids, []), action=g.action, text=g.text, status=g.status,
        turn_count=len(_loads(g.advisor_turns, [])),
        created_at=g.created_at, updated_at=g.updated_at, handled_at=g.handled_at,
    )


def _groups(db: Session, upload_id: int) -> List[WarningGroup]:
    return db.query(WarningGroup).filter(WarningGroup.upload_id == upload_id).order_by(WarningGroup.id).all()


def compute_flag_states(db: Session, upload: Upload) -> FlagStatesOut:
    """Per-flag state from the groups plus current flags. Reused by T15 (confirm) and gating_summary."""
    firing = _current_errors(upload)
    # Later groups win; a non-handled group beats a handled one for the same flag.
    by_flag: Dict[str, WarningGroup] = {}
    for g in _groups(db, upload.id):
        for fid in _loads(g.flag_ids, []):
            prev = by_flag.get(fid)
            if prev is None or prev.status == "handled" or g.status != "handled":
                by_flag[fid] = g
    out: List[FlagStateOut] = []
    stored = _stored_flags(upload)
    new_errors = [f for i, f in (firing or {}).items() if i not in {s["id"] for s in stored}]
    for f in stored + new_errors:
        fid, sev = f["id"], f.get("severity", "WARNING")
        g = by_flag.get(fid)
        if sev == "ERROR" and firing is not None and fid not in firing:
            state = "resolved"
        elif g is None:
            # Legacy acknowledgement never clears an ERROR (T14 mirrors handled ERROR groups there too).
            state = "handled" if sev != "ERROR" and _legacy_acked(upload, f) else "unhandled"
        elif sev == "ERROR" and g.status == "handled":
            state = "discussing"  # handled but the check still fires
        else:
            state = g.status
        out.append(FlagStateOut(flag_id=fid, severity=sev, state=state,
                                group_id=g.id if g else None, action=g.action if g else None))
    return FlagStatesOut(
        upload_id=upload.id, flags=out,
        unhandled_warning_count=sum(1 for s in out if s.severity == "WARNING" and s.state in ("unhandled", "open", "discussing")),
        unresolved_error_count=sum(1 for s in out if s.severity == "ERROR" and s.state != "resolved"),
    )


def gating_summary(db: Session, upload: Upload) -> GatingOut:
    """The single definition of "may leave data review": every WARNING handled (group or legacy
    acknowledgement) and no ERROR still firing on the cleaned data. Used by the resume payload,
    _derive_current_screen, the run-plan gate, recommend-plan, advance_if_clear and the PATCH
    acknowledged-flags path. advisor_available is filled by the caller that knows the provider."""
    st = compute_flag_states(db, upload)
    pending_choice = upload.handoff_status == "pending_choice"
    return GatingOut(
        unhandled_warning_count=st.unhandled_warning_count,
        unresolved_error_count=st.unresolved_error_count,
        open_group_count=sum(1 for g in _groups(db, upload.id) if g.status != "handled"),
        can_continue=st.unhandled_warning_count == 0 and st.unresolved_error_count == 0 and not pending_choice,
        handoff_status=upload.handoff_status if upload.handoff_status in _HANDOFF_STATUSES else "none",
        pending_choice=pending_choice,
    )


def advance_if_clear(db: Session, upload: Upload) -> None:
    """Move the project to "plan" once gating_summary says the user can continue."""
    from api.routers.projects import PHASES, advance_phase
    project = db.get(Project, upload.project_id)
    if not project:
        return
    phase = project.workflow_phase or "intake"
    curr_idx = PHASES.index(phase) if phase in PHASES else 0
    if curr_idx >= PHASES.index("review") and gating_summary(db, upload).can_continue:
        advance_phase(db, project, "plan")


def mark_group_handled(db: Session, upload: Upload, group: WarningGroup) -> None:
    """Set a group handled, mirror its flags into Upload.acknowledged_flags (idempotent), then advance."""
    now = datetime.utcnow()
    group.status, group.handled_at, group.updated_at = "handled", now, now
    ids = set(_loads(group.flag_ids, []))
    acked = _loads(upload.acknowledged_flags, []) or []
    have = {json.dumps(f, sort_keys=True) for f in acked}
    for f in _stored_flags(upload):
        key = json.dumps(f, sort_keys=True)
        if f["id"] in ids and key not in have:
            acked.append(f)
            have.add(key)
    upload.acknowledged_flags = json.dumps(acked)
    db.commit()
    advance_if_clear(db, upload)


def _cancellable(upload: Upload, g: WarningGroup) -> bool:
    """An unconfirmed Clarify group: not handled and none of its flags has an applied step."""
    if g.action != "clarify" or g.status not in ("open", "discussing"):
        return False
    ids = set(_loads(g.flag_ids, []))
    return not any(ids & set(s.get("warning_ids") or []) for s in _loads(upload.handoff_steps, []) if isinstance(s, dict))


def _delete_group(db: Session, upload: Upload, user: User, g: WarningGroup, superseded: bool = False) -> None:
    log_action(db, upload.project_id, "warning_group_cancelled",
               {"upload_id": upload.id, "group_id": g.id, "user_id": user.id, "superseded": superseded})
    db.delete(g)
    db.commit()


def _create_group(db: Session, upload: Upload, user: User, flag_ids: List[str], action: str, text: Optional[str]) -> WarningGroup:
    if len(set(flag_ids)) != len(flag_ids):
        flag_ids = list(dict.fromkeys(flag_ids))
    states = {s.flag_id: s for s in compute_flag_states(db, upload).flags}
    unknown = [i for i in flag_ids if i not in states]
    if unknown:
        raise _err(422, "unknown_flag_id", "Some selected warnings are not in this upload.", unknown)
    if action == "acknowledge":
        errors = [i for i in flag_ids if states[i].severity == "ERROR"]
        if errors:
            raise _err(422, "error_flag_requires_clarify", "ERROR flags can only be handled through Clarify.", errors)
    taken = [i for i in flag_ids if states[i].state != "unhandled"]
    if taken and action == "acknowledge":
        # An unconfirmed Clarify group must not trap its warnings when the advisor is unavailable.
        by_id = {g.id: g for g in _groups(db, upload.id)}
        old = [by_id.get(states[i].group_id) for i in taken]
        if all(g is not None and _cancellable(upload, g) for g in old):
            for g in {g.id: g for g in old}.values():
                _delete_group(db, upload, user, g, superseded=True)
            taken = []
    if taken:
        raise _err(409, "flag_already_grouped", "Some selected warnings are already handled or in a group.", taken)
    now = datetime.utcnow()
    group = WarningGroup(
        project_id=upload.project_id, upload_id=upload.id, flag_ids=json.dumps(flag_ids),
        action=action, text=text, status="open", advisor_turns="[]",
        created_by_user_id=user.id, created_at=now, updated_at=now,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    if action == "acknowledge":
        mark_group_handled(db, upload, group)
        db.refresh(group)
    log_action(db, upload.project_id, "warning_group_created",
               {"upload_id": upload.id, "group_id": group.id, "action": action, "flag_count": len(flag_ids)})
    return group


@router.post("/{upload_id}/warning-groups", response_model=WarningGroupOut, status_code=201)
def create_warning_group(upload_id: int, body: WarningGroupCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    return _group_out(_create_group(db, upload, user, body.flag_ids, body.action, body.text))


@router.post("/{upload_id}/warnings/acknowledge", response_model=WarningGroupOut, status_code=201)
def acknowledge_warnings(upload_id: int, body: WarningBatchAcknowledge, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    return _group_out(_create_group(db, upload, user, body.flag_ids, "acknowledge", body.text))


@router.get("/{upload_id}/warning-groups", response_model=WarningGroupListOut)
def list_warning_groups(upload_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    return WarningGroupListOut(upload_id=upload.id, groups=[_group_out(g) for g in _groups(db, upload.id)])


@router.delete("/{upload_id}/warning-groups/{group_id}", response_model=FlagStatesOut)
def cancel_warning_group(upload_id: int, group_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    g = db.get(WarningGroup, group_id)
    if not g or g.upload_id != upload.id:
        raise HTTPException(status_code=404, detail="Warning group not found")
    if not _cancellable(upload, g):
        raise _err(409, "group_not_cancellable",
                   "Only a Clarify group that has not been confirmed can be cancelled. Use revise or undo for changes already applied.")
    _delete_group(db, upload, user, g)
    return compute_flag_states(db, upload)


@router.get("/{upload_id}/flag-states", response_model=FlagStatesOut)
def get_flag_states(upload_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return compute_flag_states(db, _require_upload_access(upload_id, db, user))


def gating_block_message(g: GatingOut) -> str:
    """Plain-English reason the user cannot continue (empty when they can)."""
    parts = []
    if g.pending_choice:
        parts.append("Choose whether to keep your earlier changes or start fresh.")
    if g.unhandled_warning_count:
        parts.append("%d data quality warning(s) still need to be acknowledged or clarified" % g.unhandled_warning_count)
    if g.unresolved_error_count:
        parts.append("%d data quality error(s) still fail the re-check on the cleaned data" % g.unresolved_error_count)
    return "; ".join(parts)
