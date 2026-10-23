from __future__ import annotations

import json

from api.database import SessionLocal
from api.models_db import Project, Upload

_PAST_REVIEW = ("plan", "execute", "results")


def advance_to_phase(project_id: int, phase: str) -> None:
    """Test-only: set Project.workflow_phase directly so a fixture-seeded project can
    exercise a gated endpoint without walking the whole UI flow. Past the review step it
    also acknowledges the stored WARNING flags, as a user who finished data review would.
    ERROR flags are left alone: only a passing re-check clears them."""
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        if p:
            p.workflow_phase = phase
            if phase in _PAST_REVIEW:
                for u in db.query(Upload).filter(Upload.project_id == project_id, Upload.status == "active"):
                    flags = json.loads(u.quality_flags or "[]")
                    u.acknowledged_flags = json.dumps([f for f in flags if f.get("severity") != "ERROR"])
            db.commit()
