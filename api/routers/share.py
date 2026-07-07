from __future__ import annotations

import io
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from api.audit import log_action, safe_notification_error
from api.auth import require_project_owner
from api.database import get_db
from api.models_api import (
    CommentPayload,
    MentorCommentAuthorIn,
    MentorCommentEditIn,
    MentorCommentOut,
    ShareCreateIn,
    ShareMutationIn,
)
from api.models_db import AnalysisRun, MentorComment, MentorShare, NotificationDelivery, Project
from api.services import notifications as notification_service

router = APIRouter(prefix="/share", tags=["share"])


def _active_filter(now: datetime):
    return MentorShare.revoked_at.is_(None), or_(MentorShare.expires_at.is_(None), MentorShare.expires_at > now)


def _active_share_or_404(token: str, db: Session) -> MentorShare:
    share = db.query(MentorShare).filter(MentorShare.token == token).first()
    now = datetime.utcnow()
    if not share or share.revoked_at is not None or (share.expires_at is not None and share.expires_at <= now):
        raise HTTPException(status_code=404, detail="Share link not found")
    return share




def _latest_run(project_id: int, db: Session) -> AnalysisRun | None:
    return (
        db.query(AnalysisRun)
        .filter(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .first()
    )


def _share_url(request: Request, token: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/mentor/{token}"


def _share_response(share: MentorShare, notification_status: str | None = None) -> dict[str, Any]:
    return {
        "token": share.token,
        "project_id": share.project_id,
        "mentor_email": share.mentor_email,
        "created_at": share.created_at.isoformat() if share.created_at else None,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "revoked_at": share.revoked_at.isoformat() if share.revoked_at else None,
        "notification_status": notification_status,
    }


def _record_notification(
    db: Session,
    *,
    project_id: int,
    share_id: int,
    kind: str,
    recipient_email: str,
    status: str,
    error_message: str | None = None,
) -> NotificationDelivery:
    delivery = NotificationDelivery(
        project_id=project_id,
        share_id=share_id,
        kind=kind,
        recipient_email=recipient_email,
        status=status,
        error_message=safe_notification_error() if status == "failed" else None,
        sent_at=datetime.utcnow() if status == "sent" else None,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def _find_existing_active_share(db: Session, project_id: int, mentor_email: str | None) -> MentorShare | None:
    now = datetime.utcnow()
    query = db.query(MentorShare).filter(MentorShare.project_id == project_id, *_active_filter(now))
    if mentor_email:
        query = query.filter(MentorShare.mentor_email == mentor_email)
    else:
        query = query.filter(MentorShare.mentor_email.is_(None))
    return query.order_by(MentorShare.created_at.desc(), MentorShare.id.desc()).first()


def _mutation_target(body: ShareMutationIn) -> tuple[str | None, str | None]:
    token = body.token.strip() if body.token else None
    mentor_email = body.mentor_email.strip().lower() if body.mentor_email else None
    if not token and not mentor_email:
        raise HTTPException(status_code=400, detail="Share mutation requires token or mentor_email")
    return token, mentor_email


def _find_share_for_mutation(db: Session, project_id: int, body: ShareMutationIn) -> MentorShare | None:
    now = datetime.utcnow()
    query = db.query(MentorShare).filter(MentorShare.project_id == project_id, *_active_filter(now))
    token, mentor_email = _mutation_target(body)
    if token:
        query = query.filter(MentorShare.token == token)
    else:
        query = query.filter(MentorShare.mentor_email == mentor_email)
    return query.order_by(MentorShare.created_at.desc(), MentorShare.id.desc()).first()


@router.post("/{project_id}/create")
def create_share(
    project_id: int,
    request: Request,
    body: Optional[ShareCreateIn] = None,
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    body = body or ShareCreateIn()
    mentor_email = body.mentor_email.strip().lower() if body.mentor_email else None
    existing = _find_existing_active_share(db, project_id, mentor_email)
    if existing:
        log_action(db, project_id, "share_existing_returned", {"share_id": existing.id, "has_mentor_email": mentor_email is not None})
        return _share_response(existing, notification_status="existing_share")

    now = datetime.utcnow()
    share = MentorShare(
        project_id=project_id,
        token=secrets.token_urlsafe(32),
        mentor_email=mentor_email,
        created_at=now,
        expires_at=body.expires_at or now + timedelta(days=30),
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    log_action(db, project_id, "share_created", {"share_id": share.id, "has_mentor_email": mentor_email is not None})

    notification_status = "not_requested"
    if mentor_email:
        try:
            notification_service.send_share_invite(
                mentor_email,
                project.title or f"Project {project_id}",
                _share_url(request, share.token),
                deadline=project.deadline,
            )
            _record_notification(
                db,
                project_id=project_id,
                share_id=share.id,
                kind="share_invite",
                recipient_email=mentor_email,
                status="sent",
            )
            log_action(db, project_id, "notification_sent", {"share_id": share.id, "kind": "share_invite"})
            notification_status = "sent"
        except Exception:  # email must not block creating a scoped review link
            _record_notification(
                db,
                project_id=project_id,
                share_id=share.id,
                kind="share_invite",
                recipient_email=mentor_email,
                status="failed",
                error_message=safe_notification_error(),
            )
            log_action(db, project_id, "notification_failed", {"share_id": share.id, "kind": "share_invite"})
            notification_status = "failed"
    return _share_response(share, notification_status=notification_status)


@router.post("/{project_id}/revoke")
def revoke_share(
    project_id: int,
    body: ShareMutationIn = Body(...),
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    share = _find_share_for_mutation(db, project_id, body)
    if not share:
        raise HTTPException(status_code=404, detail="Active share not found")
    share.revoked_at = datetime.utcnow()
    db.commit()
    db.refresh(share)
    log_action(db, project_id, "share_revoked", {"share_id": share.id})
    return _share_response(share)


@router.post("/{project_id}/regenerate")
def regenerate_share(
    project_id: int,
    body: ShareMutationIn = Body(...),
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    old_share = _find_share_for_mutation(db, project_id, body)
    if not old_share:
        raise HTTPException(status_code=404, detail="Active share not found")
    old_share.revoked_at = datetime.utcnow()
    new_share = MentorShare(
        project_id=project_id,
        token=secrets.token_urlsafe(32),
        mentor_email=old_share.mentor_email,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        regenerated_from_id=old_share.id,
    )
    db.add(new_share)
    db.commit()
    db.refresh(new_share)
    log_action(db, project_id, "share_regenerated", {"share_id": new_share.id, "regenerated_from_id": old_share.id})
    return _share_response(new_share)


@router.get("/view/{token}")
def mentor_view(token: str, db: Session = Depends(get_db)):
    from api.routers.report import _build_context

    share = _active_share_or_404(token, db)
    project = db.get(Project, share.project_id)
    run = _latest_run(share.project_id, db)
    context = _build_context(run, db) if run else None
    result = context["result"] if context else {}
    flags = context["flags"] if context else []
    comments = (
        db.query(MentorComment)
        .filter(MentorComment.share_id == share.id, MentorComment.deleted_at.is_(None))
        .order_by(MentorComment.created_at.asc(), MentorComment.id.asc())
        .all()
    )
    normalized_comments = [MentorCommentOut.model_validate(comment).model_dump(mode="json") for comment in comments]
    return {
        "project": {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "deadline": project.deadline,
        } if project else {},
        "share": _share_response(share),
        "template": run.template if run else None,
        "methods": result.get("methods", ""),
        "result_summary": result.get("result_summary", ""),
        "interpretation": context["interpretation"] if context else result.get("interpretation", ""),
        "table": result.get("table", []),
        "figure_base64": result.get("figure_base64"),
        "caption": context["caption"] if context else "",
        "limitations": flags,
        "code_r": run.code_r if run else "",
        "code_spss": run.code_spss if run else "",
        "code_sas": run.code_sas if run else "",
        "report_urls": {
            "docx": f"/share/view/{token}/report/docx",
            "pdf": f"/share/view/{token}/report/pdf",
        },
        "comments": normalized_comments,
    }


@router.post("/view/{token}/comment", response_model=MentorCommentOut)
def add_comment(token: str, payload: CommentPayload, db: Session = Depends(get_db)):
    share = _active_share_or_404(token, db)
    comment = MentorComment(
        share_id=share.id,
        project_id=share.project_id,
        author_name=payload.author_name,
        author_email=payload.author_email.strip().lower() if payload.author_email else None,
        text=payload.text,
        created_at=datetime.utcnow(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    log_action(db, share.project_id, "mentor_comment_created", {"share_id": share.id, "comment_id": comment.id, "public": True})
    return comment


@router.patch("/view/{token}/comment/{comment_id}", response_model=MentorCommentOut)
def edit_public_comment(token: str, comment_id: int, payload: MentorCommentEditIn, db: Session = Depends(get_db)):
    share = _active_share_or_404(token, db)
    comment = db.get(MentorComment, comment_id)
    if not comment or comment.share_id != share.id or comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Comment not found")
    author_email = payload.author_email.strip().lower() if payload.author_email else None
    if not comment.author_email or comment.author_email != author_email:
        raise HTTPException(status_code=403, detail="Comment author email required")
    comment.text = payload.text
    comment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(comment)
    log_action(db, share.project_id, "mentor_comment_edited", {"share_id": share.id, "comment_id": comment.id, "public": True})
    return comment


@router.delete("/view/{token}/comment/{comment_id}")
def delete_public_comment(
    token: str,
    comment_id: int,
    payload: MentorCommentAuthorIn,
    db: Session = Depends(get_db),
):
    share = _active_share_or_404(token, db)
    comment = db.get(MentorComment, comment_id)
    if not comment or comment.share_id != share.id or comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Comment not found")
    author_email = payload.author_email.strip().lower() if payload.author_email else None
    if not comment.author_email or comment.author_email != author_email:
        raise HTTPException(status_code=403, detail="Comment author email required")
    comment.deleted_at = datetime.utcnow()
    db.commit()
    log_action(db, share.project_id, "mentor_comment_deleted", {"share_id": share.id, "comment_id": comment.id, "public": True})
    return {"ok": True}


@router.patch("/{project_id}/comment/{comment_id}", response_model=MentorCommentOut)
def owner_edit_comment(
    project_id: int,
    comment_id: int,
    payload: MentorCommentEditIn,
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    comment = db.get(MentorComment, comment_id)
    if not comment or comment.project_id != project_id or comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.text = payload.text
    comment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(comment)
    log_action(db, project_id, "mentor_comment_edited", {"comment_id": comment.id, "public": False})
    return comment


@router.delete("/{project_id}/comment/{comment_id}")
def owner_delete_comment(
    project_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    comment = db.get(MentorComment, comment_id)
    if not comment or comment.project_id != project_id or comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.deleted_at = datetime.utcnow()
    db.commit()
    log_action(db, project_id, "mentor_comment_deleted", {"comment_id": comment.id, "public": False})
    return {"ok": True}


@router.get("/view/{token}/report/docx")
def mentor_download_docx(token: str, db: Session = Depends(get_db)):
    from api.routers.report import _build_docx

    share = _active_share_or_404(token, db)
    run = _latest_run(share.project_id, db)
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    content = _build_docx(run, db, share_id=share.id)
    log_action(db, share.project_id, "mentor_report_downloaded", {"share_id": share.id, "run_id": run.id, "format": "docx"})
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=mentor-report-{run.id}.docx"},
    )


@router.get("/view/{token}/report/pdf")
def mentor_download_pdf(token: str, db: Session = Depends(get_db)):
    from api.routers.report import _build_pdf

    share = _active_share_or_404(token, db)
    run = _latest_run(share.project_id, db)
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    content = _build_pdf(run, db, share_id=share.id)
    log_action(db, share.project_id, "mentor_report_downloaded", {"share_id": share.id, "run_id": run.id, "format": "pdf"})
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=mentor-report-{run.id}.pdf"},
    )
