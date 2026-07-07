from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.audit import log_action, safe_notification_error
from api.auth import require_admin
from api.database import get_db
from api.models_db import MentorShare, NotificationDelivery, Project, User
from api.services import notifications as notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _parse_deadline(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _mentor_url(request: Request, token: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/mentor/{token}"


def _already_sent(db: Session, share_id: int, recipient_email: str, kind: str) -> bool:
    return (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.share_id == share_id,
            NotificationDelivery.recipient_email == recipient_email,
            NotificationDelivery.kind == kind,
            NotificationDelivery.status == "sent",
        )
        .first()
        is not None
    )


def _record_delivery(
    db: Session,
    *,
    project_id: int,
    share_id: int,
    kind: str,
    recipient_email: str,
    status: str,
    error_message: str | None = None,
) -> None:
    db.add(
        NotificationDelivery(
            project_id=project_id,
            share_id=share_id,
            kind=kind,
            recipient_email=recipient_email,
            status=status,
            error_message=safe_notification_error() if status == "failed" else None,
            sent_at=datetime.utcnow() if status == "sent" else None,
        )
    )
    db.commit()


@router.post("/deadline-reminders/run")
def run_deadline_reminders(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    today = date.today()
    cutoff = today + timedelta(days=7)
    now = datetime.utcnow()
    sent = failed = skipped = 0

    shares = (
        db.query(MentorShare)
        .filter(
            MentorShare.mentor_email.is_not(None),
            MentorShare.revoked_at.is_(None),
            (MentorShare.expires_at.is_(None)) | (MentorShare.expires_at > now),
        )
        .all()
    )
    for share in shares:
        project = db.get(Project, share.project_id)
        if not project:
            skipped += 1
            continue
        deadline = _parse_deadline(project.deadline)
        if not deadline or deadline < today or deadline > cutoff:
            skipped += 1
            continue
        kind = f"deadline_reminder:{deadline.isoformat()}"
        if _already_sent(db, share.id, share.mentor_email, kind):
            skipped += 1
            continue
        try:
            notification_service.send_deadline_reminder(
                share.mentor_email,
                deadline.isoformat(),
                project.title or f"Project {project.id}",
                _mentor_url(request, share.token),
            )
            _record_delivery(
                db,
                project_id=project.id,
                share_id=share.id,
                kind=kind,
                recipient_email=share.mentor_email,
                status="sent",
            )
            log_action(db, project.id, "notification_sent", {"share_id": share.id, "kind": kind})
            sent += 1
        except Exception:
            _record_delivery(
                db,
                project_id=project.id,
                share_id=share.id,
                kind=kind,
                recipient_email=share.mentor_email,
                status="failed",
                error_message=safe_notification_error(),
            )
            log_action(db, project.id, "notification_failed", {"share_id": share.id, "kind": kind})
            failed += 1
    return {"sent": sent, "failed": failed, "skipped": skipped}
