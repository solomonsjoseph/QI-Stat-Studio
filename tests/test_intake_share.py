"""Tests for intake and share routers."""
import os
os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from fastapi.testclient import TestClient
from api.main import app
from api.database import engine, Base, SessionLocal
from api.models_db import Project, MentorShare

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _make_project():
    db = SessionLocal()
    p = Project(title="Test", description="desc")
    db.add(p); db.commit(); pid = p.id; db.close()
    return pid


def test_save_and_get_answers():
    pid = _make_project()
    resp = client.post(f"/intake/{pid}", json={"answers": {
        "q2": "Average (mean or median)",
        "q7": {"description": "New protocol", "date": "2025-01-01"},
    }})
    assert resp.status_code == 200

    resp2 = client.get(f"/intake/{pid}")
    data = resp2.json()
    assert data["answers"]["q2"] == "Average (mean or median)"
    assert data["intervention_date"] == "2025-01-01"


def test_q10_auto_creates_share():
    pid = _make_project()
    resp = client.post(f"/intake/{pid}", json={"answers": {
        "q10": "mentor@hospital.edu, 2026-09-01",
    }})
    assert resp.status_code == 200

    db = SessionLocal()
    share = db.query(MentorShare).filter_by(project_id=pid).first()
    db.close()
    assert share is not None
    assert share.mentor_email == "mentor@hospital.edu"


def test_q10_sets_deadline():
    pid = _make_project()
    client.post(f"/intake/{pid}", json={"answers": {"q10": "2026-10-15"}})
    db = SessionLocal()
    project = db.query(Project).filter_by(id=pid).first()
    db.close()
    assert project.deadline == "2026-10-15"


def test_create_share_and_view():
    pid = _make_project()
    resp = client.post(f"/share/{pid}/create", params={"mentor_email": "doc@med.edu"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    assert len(token) > 10

    view = client.get(f"/share/view/{token}")
    assert view.status_code == 200
    assert "project" in view.json()


def test_mentor_comment():
    pid = _make_project()
    token = client.post(f"/share/{pid}/create").json()["token"]
    resp = client.post(f"/share/view/{token}/comment", json={"author": "Dr. Smith", "text": "Great work!"})
    assert resp.status_code == 200
    assert resp.json()["comment_count"] == 1
