from __future__ import annotations

from api.database import SessionLocal
from api.models_db import Project


def advance_to_phase(project_id: int, phase: str) -> None:
    """Test-only: set Project.workflow_phase directly so a fixture-seeded project can
    exercise a gated endpoint without walking the whole UI flow."""
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        if p:
            p.workflow_phase = phase
            db.commit()
