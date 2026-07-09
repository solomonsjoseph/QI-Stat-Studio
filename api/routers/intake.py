import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import require_project_owner
from api.database import get_db
from api.intake_schema import is_unsure_answer, validate_answers
from api.models_api import AnswerPayload, ShareCreateIn
from api.models_db import IntakeAnswer, Project
from api.routers.share import create_share

router = APIRouter(prefix="/intake", tags=["intake"])
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _parse_answer(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _load_answers(db: Session, project_id: int) -> dict[str, Any]:
    rows = db.query(IntakeAnswer).filter_by(project_id=project_id).all()
    return {row.question_key: _parse_answer(row.answer) for row in rows}


def _upsert(db: Session, project_id: int, key: str, value: Any):
    row = db.query(IntakeAnswer).filter_by(project_id=project_id, question_key=key).first()
    stored = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    unsure = is_unsure_answer(value)
    if row:
        row.answer = stored
        row.is_unsure = unsure
    else:
        db.add(IntakeAnswer(project_id=project_id, question_key=key, answer=stored, is_unsure=unsure))


@router.post("/{project_id}")
def save_answers(
    project_id: int,
    payload: AnswerPayload,
    request: Request,
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    existing_answers = _load_answers(db, project_id)
    answers, keys_to_delete = validate_answers(payload.answers, existing_answers)

    if keys_to_delete:
        db.query(IntakeAnswer).filter(
            IntakeAnswer.project_id == project_id,
            IntakeAnswer.question_key.in_(keys_to_delete),
        ).delete(synchronize_session=False)

    for key, value in answers.items():
        _upsert(db, project_id, key, value)

    # Q10 mentor email/deadline: guide Section 5 "Mentor auto-receives share link.
    # Tool schedules deadline reminders." Deadline is stored on the project; a
    # mentor email auto-creates (or reuses) the share link through the same path
    # /share/{project_id}/create uses, so dedup/notification logic lives in one place.
    q10_raw = answers.get("q10", payload.answers.get("q10", ""))
    q10_str = json.dumps(q10_raw) if isinstance(q10_raw, dict) else str(q10_raw)
    date_match = _DATE_RE.search(q10_str)

    if date_match:
        project.deadline = date_match.group()

    q10_email = q10_raw.get("email") if isinstance(q10_raw, dict) else None
    if q10_email:
        create_share(project_id, request, ShareCreateIn(mentor_email=q10_email), db, project)

    log_action(db, project_id, "intake_answers_saved", {"question_keys": sorted(answers.keys())})
    db.commit()
    return {"status": "saved", "project_id": project_id}


@router.get("/{project_id}")
def get_answers(
    project_id: int,
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    answers = _load_answers(db, project_id)
    intervention_date: Optional[str] = None

    val = answers.get("q7")
    if isinstance(val, dict) and "date" in val:
        intervention_date = val["date"]
    elif isinstance(val, str):
        d = _DATE_RE.search(val)
        if d:
            intervention_date = d.group()

    return {"project_id": project_id, "answers": answers, "intervention_date": intervention_date}
