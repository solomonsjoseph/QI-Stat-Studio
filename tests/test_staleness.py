import json
import pytest

from api.database import SessionLocal
from api.models_db import Project, Upload


def _register(client, email="stale_test@example.com"):
    client.post("/auth/register", json={"email": email, "password": "password123"})


def test_changing_description_marks_plan_stale_and_clears_collection_notes(auth_client):
    _register(auth_client, "staleness@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Stale Test", "description": "Original description of project"},
        files={"file": ("data.csv", b"month,falls\n2024-01,5\n", "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["project"]["id"]

    # Seed plan and data_collection_notes
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.ai_analysis_plan = json.dumps({"analyses": [{"template": "run_chart"}], "confirmed": True, "stale": False})
        p.data_collection_notes = json.dumps({"recommendations": ["collect more dates"]})
        db.commit()

    # Now update description
    patch_resp = auth_client.patch(f"/projects/{pid}", json={"description": "Changed description radically"})
    assert patch_resp.status_code == 200

    # Verify downstream state is marked stale
    with SessionLocal() as db:
        p = db.get(Project, pid)
        plan = json.loads(p.ai_analysis_plan or "{}")
        assert plan.get("stale") is True
        assert p.data_collection_notes is None
        clarify = json.loads(p.ai_clarification_state or "{}")
        if clarify:
            assert clarify.get("stale") is True
