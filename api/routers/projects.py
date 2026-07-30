from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import get_current_user, require_admin, require_project_owner
from api.database import get_db
from api.models_api import (
    AnalysisRunOut,
    EditIn,
    ProjectCreate,
    ProjectListResponse,
    ProjectOut,
    ProjectResumeOut,
    ProjectUpdate,
    ShareOut,
    UploadOut,
)
from api.models_db import (
    AnalysisRun,
    AuditLog,
    EditHistory,
    IntakeAnswer,
    MentorShare,
    Project,
    Upload,
    User,
)
from api.routers.share import _active_filter

router = APIRouter(prefix="/projects", tags=["projects"])




def _parse_json(raw: str | None, fallback: Any):
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _answer_value(raw: str | None):
    try:
        return json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return raw


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
        quality_flags=_parse_json(upload.quality_flags, []),
        acknowledged_flags=_parse_json(upload.acknowledged_flags, None),
        status=upload.status,
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


def _load_answers(db: Session, project_id: int) -> dict[str, Any]:
    rows = db.query(IntakeAnswer).filter_by(project_id=project_id).all()
    return {row.question_key: _answer_value(row.answer) for row in rows}


def _has_unacknowledged_flags(upload: Upload | None) -> bool:
    if not upload:
        return False
    flags = _parse_json(upload.quality_flags, [])
    if not flags:
        return False
    acknowledged = _parse_json(upload.acknowledged_flags, []) or []
    acknowledged_keys = {json.dumps(flag, sort_keys=True) for flag in acknowledged}
    return any(json.dumps(flag, sort_keys=True) not in acknowledged_keys for flag in flags)


def _missing_intake_answer(answers: dict[str, Any], key: str) -> bool:
    if key not in answers:
        return True
    value = answers.get(key)
    if key in {"q7", "q10"}:
        return value in (None, "")
    return value in (None, "", {})


def _derive_current_screen(db: Session, project: Project, answers: dict[str, Any], latest_upload: Upload | None, latest_run: AnalysisRun | None) -> str:
    if not (answers.get("q1") or project.description):
        return "description"

    no_comparison = answers.get("q3") == "No — I'm just describing one time period"
    required = ["q2", "q3", "q4", "q5", "q6", "q9", "q10"]
    if not no_comparison:
        required.extend(["q7", "q8"])
    if any(_missing_intake_answer(answers, key) for key in required):
        return "intake"

    if not latest_upload:
        return "upload"
    if _has_unacknowledged_flags(latest_upload):
        return "review"
    if not latest_run:
        return "analysis"

    interpretation_edit = (
        db.query(EditHistory)
        .filter(EditHistory.project_id == project.id, EditHistory.field == "interpretation")
        .first()
    )
    if not interpretation_edit:
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
    answers = _load_answers(db, project.id)
    latest_upload = (
        db.query(Upload)
        .filter(Upload.project_id == project.id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )
    run_query = db.query(AnalysisRun).filter(AnalysisRun.project_id == project.id)
    if latest_upload:
        run_query = run_query.filter(AnalysisRun.upload_id == latest_upload.id)
    latest_run = run_query.order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc()).first()
    latest_share = (
        db.query(MentorShare)
        .filter(MentorShare.project_id == project.id, *_active_filter(datetime.utcnow()))
        .order_by(MentorShare.created_at.desc(), MentorShare.id.desc())
        .first()
    )
    return ProjectResumeOut(
        project=project,
        answers=answers,
        latest_upload=_upload_out(latest_upload),
        latest_run=_run_out(latest_run),
        latest_share=_share_out(latest_share),
        current_screen=_derive_current_screen(db, project, answers, latest_upload, latest_run),
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
    db.commit()
    db.refresh(project)
    log_action(db, project.id, "project_updated", {"fields": sorted(changes)})
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
    db.add(
        EditHistory(
            project_id=project.id,
            field=body.field,
            original_text=body.original_text,
            edited_text=body.edited_text,
        )
    )
    if body.field == "title":
        project.title = body.edited_text
    db.add(AuditLog(project_id=project_id, action="field_edited", metadata_json=json.dumps({"field": body.field})))
    db.commit()
    return {"ok": True}
