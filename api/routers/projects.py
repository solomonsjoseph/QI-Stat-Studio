from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import get_current_user, require_admin, require_project_owner
from api.database import get_db
from api.models_api import (
    AnalysisRunOut,
    EditIn,
    ProjectCreate,
    ProjectDesign,
    ProjectListResponse,
    ProjectOut,
    ProjectResumeOut,
    ProjectUpdate,
    ShareOut,
    UploadOut,
)
from api.project_design import merge_user_design, validate_design_columns
from api.models_db import (
    AnalysisRun,
    AuditLog,
    EditHistory,
    MentorShare,
    Project,
    Upload,
    User,
)
from api.routers.share import _active_filter
from api.routers.upload import _enforce_phi_gate, _read_dictionary_file, _read_validated_upload_file, _store_upload
from api.staleness import check_and_apply_inputs_fingerprint, compute_inputs_fingerprint

router = APIRouter(prefix="/projects", tags=["projects"])

PHASES = ["intake", "clarify", "review", "plan", "execute", "results"]


def require_phase(db: Session, project: Project, minimum: str) -> None:
    """Raise HTTPException(409, {"message": ..., "required_phase": minimum}) when the
    project has not yet reached `minimum`."""
    curr_phase = project.workflow_phase or "intake"
    if curr_phase not in PHASES:
        curr_phase = "intake"
    if minimum not in PHASES:
        return
    if PHASES.index(curr_phase) < PHASES.index(minimum):
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Project must reach phase '{minimum}' before this action. Current phase is '{curr_phase}'.",
                "required_phase": minimum,
                "current_phase": curr_phase,
            },
        )


def advance_phase(db: Session, project: Project, phase: str) -> None:
    """Monotonic: never moves a project backwards."""
    if phase not in PHASES:
        return
    curr_phase = project.workflow_phase or "intake"
    curr_idx = PHASES.index(curr_phase) if curr_phase in PHASES else 0
    target_idx = PHASES.index(phase)
    if target_idx > curr_idx:
        project.workflow_phase = phase
        db.commit()




def _parse_json(raw: str | None, fallback: Any):
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback



def _upload_out(upload: Upload | None) -> UploadOut | None:
    if not upload:
        return None
    return UploadOut(
        id=upload.id,
        project_id=upload.project_id,
        filename=upload.filename,
        original_filename=upload.original_filename or upload.filename,
        file_type=upload.file_type,
        size_bytes=upload.size_bytes,
        checksum_sha256=upload.checksum_sha256,
        created_at=upload.created_at,
        col_types=_parse_json(upload.col_types, {}),
        column_map=_parse_json(upload.column_map, {}),
        column_roles=_parse_json(upload.column_roles, {}),
        quality_flags=_parse_json(upload.quality_flags, []),
        acknowledged_flags=_parse_json(upload.acknowledged_flags, None),
        status=upload.status,
        dataset_profile=_parse_json(upload.dataset_profile, None),
    )


def _run_out(run: AnalysisRun | None) -> AnalysisRunOut | None:
    if not run:
        return None
    return AnalysisRunOut(
        id=run.id,
        project_id=run.project_id,
        upload_id=run.upload_id,
        template=run.template,
        parameters=_parse_json(run.parameters, {}),
        result=_parse_json(run.result_json, {}),
        created_at=run.created_at,
    )


def _share_out(share: MentorShare | None) -> ShareOut | None:
    if not share:
        return None
    return ShareOut.model_validate(share)


def _has_unacknowledged_flags(upload: Upload | None) -> bool:
    if not upload:
        return False
    flags = _parse_json(upload.quality_flags, [])
    if not flags:
        return False
    acknowledged = _parse_json(upload.acknowledged_flags, []) or []
    acknowledged_keys = {json.dumps(flag, sort_keys=True) for flag in acknowledged}
    return any(json.dumps(flag, sort_keys=True) not in acknowledged_keys for flag in flags)


def _derive_current_screen(db: Session, project: Project, latest_upload: Upload | None, runs: list[AnalysisRun]) -> str:
    if not project.description or not latest_upload:
        return "description"
    if not json.loads(project.ai_clarification_state or "{}").get("confirmed"):
        return "clarify"
    if _has_unacknowledged_flags(latest_upload):
        return "review"
    plan = json.loads(project.ai_analysis_plan or "{}")
    if not plan.get("confirmed") or not runs:
        return "analysis"
    if not db.query(EditHistory).filter(EditHistory.project_id == project.id,
                                        EditHistory.field == "interpretation").first():
        return "edit"
    return "download"


@router.post("", response_model=ProjectOut)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = Project(
        owner_user_id=user.id,
        title=body.title,
        description=body.description,
        deadline=body.deadline,
        status="draft",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    log_action(db, p.id, "project_created")
    return p


@router.post("/intake")
async def create_project_intake(
    title: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    dictionary: UploadFile | None = File(None),
    deadline: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unified intake: title/description + dataset + optional data dictionary in one step."""
    parsed_deadline: str | None = None
    if deadline and deadline.strip():
        try:
            parsed_deadline = str(datetime.fromisoformat(deadline.strip()).date())
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail={"message": "Invalid deadline format", "field_errors": {"deadline": ["Invalid date format (expected YYYY-MM-DD)"]}},
            )

    original_filename, _file_type, raw, df, restored_cols = await _read_validated_upload_file(file)
    dictionary_filename, dictionary_text = await _read_dictionary_file(dictionary)
    _enforce_phi_gate(df, dictionary_text)

    project = Project(
        owner_user_id=user.id,
        title=title,
        description=description,
        status="draft",
        deadline=parsed_deadline,
        workflow_phase="clarify",
    )
    db.add(project)
    db.flush()
    upload, *_ = _store_upload(
        db, project.id, original_filename, raw, df, restored_cols, dictionary_filename, dictionary_text
    )
    project.inputs_fingerprint = compute_inputs_fingerprint(project, upload)
    db.commit()
    db.refresh(project)
    db.refresh(upload)
    log_action(db, project.id, "project_created")
    log_action(db, project.id, "upload_created", {"upload_id": upload.id, "file_type": upload.file_type, "size_bytes": upload.size_bytes})
    return {"project": ProjectOut.model_validate(project), "upload": _upload_out(upload)}


@router.get("", response_model=ProjectListResponse)
def list_projects(
    limit: int = 25,
    offset: int = 0,
    status: Optional[str] = None,
    order: Literal["created_desc", "created_asc", "title_asc"] = "created_desc",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    query = db.query(Project)
    if user.role != "admin":
        query = query.filter(Project.owner_user_id == user.id)
    if status is None:
        query = query.filter(Project.status != "archived")
    else:
        query = query.filter(Project.status == status)

    total = query.with_entities(func.count(Project.id)).scalar() or 0
    if order == "created_asc":
        query = query.order_by(Project.created_at.asc(), Project.id.asc())
    elif order == "title_asc":
        query = query.order_by(Project.title.asc(), Project.id.asc())
    else:
        query = query.order_by(Project.created_at.desc(), Project.id.desc())
    return ProjectListResponse(items=query.offset(offset).limit(limit).all(), total=total, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project: Project = Depends(require_project_owner)):
    return project


@router.get("/{project_id}/resume", response_model=ProjectResumeOut)
def resume_project(project: Project = Depends(require_project_owner), db: Session = Depends(get_db)):
    latest_upload = (
        db.query(Upload)
        .filter(Upload.project_id == project.id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )
    run_query = db.query(AnalysisRun).filter(AnalysisRun.project_id == project.id)
    if latest_upload:
        run_query = run_query.filter(AnalysisRun.upload_id == latest_upload.id)
    runs = run_query.order_by(AnalysisRun.created_at.asc(), AnalysisRun.id.asc()).all()
    latest_run = runs[-1] if runs else None
    latest_share = (
        db.query(MentorShare)
        .filter(MentorShare.project_id == project.id, *_active_filter(datetime.utcnow()))
        .order_by(MentorShare.created_at.desc(), MentorShare.id.desc())
        .first()
    )
    from api.routers.report import run_hydration_dict

    runs_out = [run_hydration_dict(r, db, raw_caption=True) for r in runs]

    return ProjectResumeOut(
        project=project,
        latest_upload=_upload_out(latest_upload),
        latest_run=_run_out(latest_run),
        runs=runs_out,
        latest_share=_share_out(latest_share),
        current_screen=_derive_current_screen(db, project, latest_upload, runs),
    )


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(body: ProjectUpdate, project: Project = Depends(require_project_owner), db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(project, field, value)
    if changes.get("status") == "archived":
        project.archived_at = datetime.utcnow()
    elif "status" in changes and changes.get("status") != "archived":
        project.archived_at = None
    latest_upload = (
        db.query(Upload)
        .filter(Upload.project_id == project.id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )
    check_and_apply_inputs_fingerprint(project, latest_upload, db)
    db.commit()
    db.refresh(project)
    log_action(db, project.id, "project_updated", {"fields": sorted(changes)})
    return project


@router.put("/{project_id}/design", response_model=ProjectOut)
def update_project_design(
    body: ProjectDesign,
    project: Project = Depends(require_project_owner),
    db: Session = Depends(get_db),
):
    latest_upload = (
        db.query(Upload)
        .filter(Upload.project_id == project.id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )
    if latest_upload:
        col_types = _parse_json(latest_upload.col_types, {})
        field_errors = validate_design_columns(body, col_types)
        if field_errors:
            raise HTTPException(
                status_code=422,
                detail={"message": "Invalid column names in project design", "field_errors": field_errors},
            )

    old_design_dict = _parse_json(project.ai_project_design, {})
    merged_design = merge_user_design(body, old_design_dict)

    project.ai_project_design = json.dumps(merged_design.model_dump())
    check_and_apply_inputs_fingerprint(project, latest_upload, db)
    db.commit()
    db.refresh(project)
    log_action(db, project.id, "design_edited")
    return project


@router.delete("/{project_id}")
def delete_project(
    purge: bool = False,
    project: Project = Depends(require_project_owner),
    db: Session = Depends(get_db),
):
    if not purge:
        project.status = "archived"
        project.archived_at = datetime.utcnow()
        db.commit()
        log_action(db, project.id, "project_archived")
        return {"ok": True, "purged": False}

    uploads = db.query(Upload).filter(Upload.project_id == project.id).all()
    for upload in uploads:
        if upload.encrypted_path:
            path = Path(upload.encrypted_path)
            if path.exists() and path.is_file():
                path.unlink()
    db.delete(project)
    db.commit()
    return {"ok": True, "purged": True}


@router.post("/{project_id}/claim", response_model=ProjectOut)
def claim_project(
    project_id: int,
    body: dict[str, int],
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_user_id is not None:
        raise HTTPException(status_code=400, detail="Project already has an owner")
    owner_id = body.get("owner_user_id")
    owner = db.get(User, owner_id) if owner_id else None
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")
    project.owner_user_id = owner.id
    db.commit()
    db.refresh(project)
    log_action(db, project.id, "project_claimed", {"owner_user_id": owner.id, "claimed_by": user.id})
    return project


@router.post("/{project_id}/edits")
def save_edit(project_id: int, body: EditIn, db: Session = Depends(get_db), project: Project = Depends(require_project_owner)):
    run_id = None
    if body.field != "title" and body.run_id is not None:
        run = db.get(AnalysisRun, body.run_id)
        if not run or run.project_id != project.id:
            raise HTTPException(status_code=404, detail="Analysis run not found for this project")
        run_id = body.run_id
    db.add(
        EditHistory(
            project_id=project.id,
            run_id=run_id,
            field=body.field,
            original_text=body.original_text,
            edited_text=body.edited_text,
        )
    )
    if body.field == "title":
        project.title = body.edited_text
    db.add(AuditLog(project_id=project_id, action="field_edited", metadata_json=json.dumps({"field": body.field, "run_id": run_id})))
    db.commit()
    return {"ok": True}
