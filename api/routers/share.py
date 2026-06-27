import json
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from api.database import get_db
from api.models_db import MentorShare, AnalysisRun, Project

router = APIRouter(prefix="/share", tags=["share"])


class CommentPayload(BaseModel):
    author: str = "mentor"
    text: str


@router.post("/{project_id}/create")
def create_share(project_id: int, mentor_email: str = "", db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    existing = db.query(MentorShare).filter_by(project_id=project_id).first()
    if existing:
        return {"token": existing.token, "project_id": project_id}
    share = MentorShare(
        project_id=project_id,
        token=secrets.token_urlsafe(32),
        mentor_email=mentor_email or None,
    )
    db.add(share); db.commit(); db.refresh(share)
    return {"token": share.token, "project_id": project_id}


@router.get("/view/{token}")
def mentor_view(token: str, db: Session = Depends(get_db)):
    share = db.query(MentorShare).filter_by(token=token).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found")
    project = db.query(Project).filter(Project.id == share.project_id).first()
    run = db.query(AnalysisRun).filter_by(project_id=share.project_id).order_by(AnalysisRun.id.desc()).first()
    result = json.loads(run.result_json) if run else {}
    return {
        "project": {"id": project.id, "title": project.title, "description": project.description} if project else {},
        "result_summary": result.get("result_summary", ""),
        "methods": result.get("methods", ""),
        "template": run.template if run else None,
        "comments": json.loads(share.comments_json),
    }


@router.post("/view/{token}/comment")
def add_comment(token: str, payload: CommentPayload, db: Session = Depends(get_db)):
    share = db.query(MentorShare).filter_by(token=token).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found")
    comments = json.loads(share.comments_json)
    comments.append({"author": payload.author, "text": payload.text})
    share.comments_json = json.dumps(comments)
    db.commit()
    return {"status": "ok", "comment_count": len(comments)}
