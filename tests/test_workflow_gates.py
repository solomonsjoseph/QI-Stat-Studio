import json
from unittest.mock import patch

import pytest

from api.database import SessionLocal
from api.models_db import Project, Upload


def _register(client, email="gates_test@example.com"):
    client.post("/auth/register", json={"email": email, "password": "password123"})


def test_clarify_before_upload_returns_409_and_no_llm_call(auth_client):
    _register(auth_client, "no_upload@example.com")
    resp = auth_client.post("/projects", json={"title": "No upload project", "description": "desc"})
    assert resp.status_code == 200
    pid = resp.json()["id"]

    # Project is in "intake" phase, no upload exists
    with patch("api.routers.ai.litellm.completion") as mock_complete:
        c_resp = auth_client.post(f"/ai/clarify/{pid}", json={})
        assert c_resp.status_code == 409
        assert mock_complete.call_count == 0
        data = c_resp.json()
        assert "clarify" in data["error"]["message"].lower() or data["error"]["field_errors"].get("required_phase") == "clarify"


def test_recommend_plan_before_acknowledgment_returns_409(auth_client):
    _register(auth_client, "no_ack@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Unacknowledged Project", "description": "desc"},
        files={"file": ("data.csv", b"month,val\n2024-01,10\n", "text/csv")},
    )
    assert resp.status_code == 200
    pid = resp.json()["project"]["id"]

    # Project advances to "clarify" on intake, but not "plan" (no flag ack yet)
    rec_resp = auth_client.post(f"/ai/recommend-plan/{pid}", json={})
    assert rec_resp.status_code == 409
    data = rec_resp.json()
    assert "plan" in data["error"]["message"].lower() or data["error"]["field_errors"].get("required_phase") == "plan"


def test_run_plan_with_unconfirmed_plan_returns_409(auth_client):
    _register(auth_client, "unconfirmed@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Unconfirmed Project", "description": "desc"},
        files={"file": ("data.csv", b"month,falls\n2024-01,2\n2024-02,3\n", "text/csv")},
    )
    assert resp.status_code == 200
    pid = resp.json()["project"]["id"]
    uid = resp.json()["upload"]["id"]

    # Set phase to plan directly, but leave ai_analysis_plan unconfirmed
    from tests.helpers import advance_to_phase
    advance_to_phase(pid, "plan")

    run_resp = auth_client.post(
        f"/analyze/run-plan/{pid}",
        json={
            "upload_id": uid,
            "analyses": [{"template": "descriptive_summary", "parameters": {"value_cols": ["falls"]}}],
        },
    )
    assert run_resp.status_code == 409
    data = run_resp.json()
    assert "confirmed" in data["error"]["message"].lower()
