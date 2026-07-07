"""Tests for authenticated intake and share router contracts."""
import os

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from api.database import SessionLocal
from api.models_db import MentorComment, MentorShare, Project

PASSWORD = "password123"


def _register(client, email="owner@example.com"):
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _make_project(client, title="Test"):
    response = client.post("/projects", json={"title": title, "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_save_and_get_answers(client):
    _register(client)
    pid = _make_project(client)

    resp = client.post(
        f"/intake/{pid}",
        json={
            "answers": {
                "q2": "An average or median value (average LDL)",
                "q7": {"description": "New protocol", "date": "2025-01-01"},
            }
        },
    )
    assert resp.status_code == 200, resp.text

    resp2 = client.get(f"/intake/{pid}")
    assert resp2.status_code == 200, resp2.text
    data = resp2.json()
    assert data["answers"]["q2"] == "An average or median value (average LDL)"
    assert data["intervention_date"] == "2025-01-01"


def test_q10_email_does_not_auto_create_share_and_deadline_is_saved(client):
    _register(client)
    pid = _make_project(client)

    resp = client.post(
        f"/intake/{pid}",
        json={"answers": {"q10": {"email": "mentor@hospital.edu", "deadline": "2026-09-01"}}},
    )
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        share = db.query(MentorShare).filter_by(project_id=pid).first()
        project = db.get(Project, pid)
        assert share is None
        assert project.deadline == "2026-09-01"


def test_q10_sets_deadline_without_mentor_email(client):
    _register(client)
    pid = _make_project(client)

    resp = client.post(f"/intake/{pid}", json={"answers": {"q10": {"deadline": "2026-10-15"}}})
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        project = db.get(Project, pid)
        assert project.deadline == "2026-10-15"


def test_create_share_and_view(client):
    _register(client)
    pid = _make_project(client)

    resp = client.post(f"/share/{pid}/create", json={})
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    assert len(token) > 10

    view = client.get(f"/share/view/{token}")
    assert view.status_code == 200, view.text
    assert view.json()["project"]["id"] == pid


def test_mentor_comment_uses_normalized_public_contract(client):
    _register(client)
    pid = _make_project(client)
    token = client.post(f"/share/{pid}/create", json={}).json()["token"]

    resp = client.post(
        f"/share/view/{token}/comment",
        json={"author_name": "Dr. Smith", "author_email": "smith@example.edu", "text": "Great work!"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["author_name"] == "Dr. Smith"
    assert data["author_email"] == "smith@example.edu"
    assert data["text"] == "Great work!"

    with SessionLocal() as db:
        comment = db.query(MentorComment).filter_by(project_id=pid).one()
        share = db.query(MentorShare).filter_by(token=token).one()
        assert comment.share_id == share.id
