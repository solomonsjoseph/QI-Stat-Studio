import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api.models_db import Project, AuditLog, EditHistory
from api.models_api import ProjectCreate, ProjectOut, EditIn

router = APIRouter(prefix="/projects", tags=["projects"])


def log_action(db: Session, project_id: int, action: str, meta: dict = {}):
    db.add(AuditLog(project_id=project_id, action=action, metadata_json=json.dumps(meta)))
    db.commit()


@router.post("", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(**body.dict())
    db.add(p)
    db.commit()
    db.refresh(p)
    log_action(db, p.id, "project_created")
    return p


@router.get("", response_model=List[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).get(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.post("/{project_id}/edits")
def save_edit(project_id: int, body: EditIn, db: Session = Depends(get_db)):
    db.add(EditHistory(project_id=project_id, field=body.field,
                       original_text="", edited_text=body.edited_text))
    db.commit()
    log_action(db, project_id, "field_edited", {"field": body.field})
    return {"ok": True}
