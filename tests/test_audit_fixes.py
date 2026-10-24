"""Independent-audit fixes: key placeholders, PHI in prompts, change-log purge, stub provider, mentor view."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api import ai_key
from api.database import SessionLocal
from api.models_db import AppSetting, Project, Upload, User
from api.routers import ai as ai_router
from tests.test_handoff_journey import DESIGN_TURN, _group, _intake, _use, make_csv

SSN = "123-45-6789"
CLEAN_CSV = b"month,infections,patients\n2024-01,2,100\n2024-02,3,110\n2024-03,1,90\n"


@pytest.fixture
def llm(monkeypatch, mock_llm):
    _use(monkeypatch, "openrouter", "k")
    return mock_llm


def _sent(llm) -> str:
    return json.dumps(llm.call_args.kwargs["messages"])


def _set_design(pid, design):
    with SessionLocal() as db:
        db.get(Project, pid).ai_project_design = json.dumps(design)
        db.commit()


# 1
@pytest.mark.parametrize("value,expected", [
    ("", None), ("sk-or-...", None), ("changeme", None), ("your-key-here", None), ("sk-or-v1-abcdef123", "sk-or-v1-abcdef123"),
])
def test_env_key_ignores_placeholders(monkeypatch, value, expected):
    monkeypatch.setattr(ai_key.settings, "openrouter_api_key", value)
    assert ai_key.env_key("openrouter") == expected


def test_env_example_has_no_placeholder_key():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    assert "OPENROUTER_API_KEY=\n" in text


# 2
def test_clarify_scrubs_project_title_and_description(auth_client, llm):
    c = auth_client
    pid, _, _ = _intake(c, make_csv(), title="Study of patient %s" % SSN)
    with SessionLocal() as db:
        db.get(Project, pid).description = "Contact patient %s about the aim." % SSN
        db.commit()
    llm.push(DESIGN_TURN)
    assert c.post("/ai/clarify/%d" % pid, json={"message": "hello"}).status_code == 200
    assert SSN not in _sent(llm)


DIRTY_DESIGN = {
    "aim": "Aim for %s" % SSN, "population": "Pop %s" % SSN, "setting": "Set %s" % SSN,
    "intervention": {"present": True, "description": "Int %s" % SSN, "start_date": "2025-01-01"},
    "plain_restatement": "Restate %s" % SSN, "comparison": "pre-post",
}


def test_collection_guidance_scrubs_design_text(auth_client, llm):
    c = auth_client
    pid, _, _ = _intake(c, CLEAN_CSV)
    _set_design(pid, DIRTY_DESIGN)
    llm.push({"recommendations": []})
    r = c.post("/ai/collection-guidance/%d" % pid)
    assert r.status_code == 200, r.text
    assert llm.called and SSN not in _sent(llm) and "2025-01-01" in _sent(llm)


def test_recommend_plan_scrubs_design_text(auth_client, llm):
    c = auth_client
    pid, _, _ = _intake(c, CLEAN_CSV)
    _set_design(pid, DIRTY_DESIGN)
    with SessionLocal() as db:
        db.get(Project, pid).workflow_phase = "plan"
        db.commit()
    llm.push({"message": "ok", "reasoning": "r", "analyses": []})
    r = c.post("/ai/recommend-plan/%d" % pid, json={})
    assert r.status_code == 200, r.text
    assert llm.called and SSN not in _sent(llm)


def test_override_plan_scrubs_design_text(auth_client, llm):
    c = auth_client
    pid, _, _ = _intake(c, CLEAN_CSV)
    _set_design(pid, DIRTY_DESIGN)
    with SessionLocal() as db:
        db.get(Project, pid).workflow_phase = "plan"
        db.commit()
    llm.push({"message": "ok", "reasoning": "r", "analyses": []})
    c.post("/ai/override-plan/%d" % pid, json={"instruction": "Add a summary."})
    assert llm.called and SSN not in _sent(llm)


# 3
def _make_log(c):
    pid, uid, _ = _intake(c, make_csv())
    with SessionLocal() as db:
        up = db.get(Upload, uid)
        up.handoff_revisions = json.dumps(json.loads(up.handoff_revisions) + [{"revision": 2, "kind": "apply"}])
        db.commit()
    return pid


def _role(email, role):
    with SessionLocal() as db:
        db.query(User).filter_by(email=email).one().role = role
        db.commit()


def test_purge_with_change_log_needs_admin(auth_client):
    c = auth_client
    pid = _make_log(c)
    _role("owner@example.com", "resident")
    r = c.delete("/projects/%d?purge=true" % pid)
    assert r.status_code == 409, r.text
    assert "change log" in r.text.lower()
    assert c.get("/projects/%d" % pid).status_code == 200  # still there
    _role("owner@example.com", "admin")
    assert c.delete("/projects/%d?purge=true" % pid).status_code == 200


def test_resident_can_purge_project_without_change_log(auth_client):
    c = auth_client
    pid, _, _ = _intake(c, make_csv())
    _role("owner@example.com", "resident")
    assert c.delete("/projects/%d?purge=true" % pid).status_code == 200


# 4
def test_stub_env_provider_ignores_runtime_override(monkeypatch):
    monkeypatch.setattr(ai_router.settings, "ai_provider", "stub")
    with SessionLocal() as db:
        db.add(AppSetting(key="ai_provider", value="openrouter"))
        db.commit()
        assert ai_router._provider_settings(db, None)[0] == "stub"
        monkeypatch.setattr(ai_router.settings, "ai_provider", "openrouter")
        assert ai_router._provider_settings(db, None)[0] == "openrouter"


# 5
def test_mentor_view_masks_emails_only_in_change_log(auth_client):
    from fastapi.testclient import TestClient
    from api.main import app

    c = auth_client
    pid, uid, _ = _intake(c, make_csv())
    c.get("/upload/%d/handoff" % uid)
    with SessionLocal() as db:
        up = db.get(Upload, uid)
        md = up.handoff_md
        assert "## Change log" in md
        up.handoff_md = md.replace("## Change log\n", "contact dict@example.org\n\n## Change log\nby log@example.org\n", 1)
        db.commit()
    token = c.post("/share/%d/create" % pid, json={}).json()["token"]
    with TestClient(app) as anon:
        out = anon.get("/share/%s/handoff" % token).json()["markdown"]
    assert "dict@example.org" in out and "log@example.org" not in out


# 7
def test_flag_states_expose_pending_choice(auth_client):
    c = auth_client
    _, uid, _ = _intake(c, make_csv())
    assert c.get("/upload/%d/flag-states" % uid).json()["pending_choice"] is False
    with SessionLocal() as db:
        db.get(Upload, uid).handoff_status = "pending_choice"
        db.commit()
    assert c.get("/upload/%d/flag-states" % uid).json()["pending_choice"] is True
