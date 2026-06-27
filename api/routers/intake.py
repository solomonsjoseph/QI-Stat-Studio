import json
import re
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from api.database import get_db
from api.models_db import IntakeAnswer, MentorShare, Project

router = APIRouter(prefix="/intake", tags=["intake"])

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class AnswerPayload(BaseModel):
    answers: dict  # {q1: ..., q2: ..., q7: {description, date} | str, q10: str, ...}


def _upsert(db, project_id, key, value):
    row = db.query(IntakeAnswer).filter_by(project_id=project_id, question_key=key).first()
    if row:
        row.answer = value
    else:
        db.add(IntakeAnswer(project_id=project_id, question_key=key, answer=value))


@router.post("/{project_id}")
def save_answers(project_id: int, payload: AnswerPayload, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for key, value in payload.answers.items():
        # Serialize composite answers (dicts) to JSON string for storage
        stored = json.dumps(value) if isinstance(value, dict) else str(value)
        _upsert(db, project_id, key, stored)

    # Q10: extract email → auto-create share; extract date → store deadline
    q10_raw = payload.answers.get("q10", "")
    q10_str = json.dumps(q10_raw) if isinstance(q10_raw, dict) else str(q10_raw)
    email_match = _EMAIL_RE.search(q10_str)
    date_match = _DATE_RE.search(q10_str)

    if email_match:
        email = email_match.group()
        existing = db.query(MentorShare).filter_by(project_id=project_id).first()
        if not existing:
            db.add(MentorShare(
                project_id=project_id,
                token=secrets.token_urlsafe(32),
                mentor_email=email,
            ))

    if date_match:
        project.deadline = date_match.group()

    db.commit()
    return {"status": "saved", "project_id": project_id}


@router.get("/{project_id}")
def get_answers(project_id: int, db: Session = Depends(get_db)):
    rows = db.query(IntakeAnswer).filter_by(project_id=project_id).all()
    answers = {}
    intervention_date: Optional[str] = None

    for row in rows:
        # Try to parse JSON-stored composite answers back
        try:
            answers[row.question_key] = json.loads(row.answer)
        except (json.JSONDecodeError, TypeError):
            answers[row.question_key] = row.answer

        # Q7 may be {"description": ..., "date": ...}
        if row.question_key == "q7":
            val = answers["q7"]
            if isinstance(val, dict) and "date" in val:
                intervention_date = val["date"]
            elif isinstance(val, str):
                d = _DATE_RE.search(val)
                if d:
                    intervention_date = d.group()

    return {"project_id": project_id, "answers": answers, "intervention_date": intervention_date}
