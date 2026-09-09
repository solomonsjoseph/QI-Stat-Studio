import json
from unittest.mock import patch
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.database import SessionLocal
from api.main import app
from api.models_db import AnalysisRun, Project, Upload
from tests.helpers import advance_to_phase


def _register(client, email="interpret_test@example.com"):
    client.post("/auth/register", json={"email": email, "password": "password123"})


def test_interpret_results_endpoint(auth_client):
    _register(auth_client, "interpret_user@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Interpret Test", "description": "Testing multi-result interpretation"},
        files={"file": ("data.csv", b"month,falls\n2024-01,2\n2024-02,3\n2024-03,1\n", "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["project"]["id"]
    uid = resp.json()["upload"]["id"]

    advance_to_phase(pid, "plan")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.ai_analysis_plan = json.dumps({"confirmed": True})
        u = db.get(Upload, uid)
        u.acknowledged_flags = u.quality_flags
        db.commit()

    # Execute plan with 2 analyses to advance phase to "results"
    plan_payload = {
        "upload_id": uid,
        "analyses": [
            {"template": "descriptive_summary", "parameters": {"value_cols": ["falls"]}},
            {"template": "run_chart", "parameters": {"date_col": "month", "value_col": "falls"}},
        ],
    }
    run_resp = auth_client.post(f"/analyze/run-plan/{pid}", json=plan_payload)
    assert run_resp.status_code == 200
    runs = run_resp.json()["runs"]
    run1_id = runs[0]["run_id"]
    run2_id = runs[1]["run_id"]

    mock_llm_reply = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "interpretations": [
                            {"run_id": run1_id, "text": "Falls averaged 2.0 per month during the baseline period."},
                            {"run_id": run2_id, "text": "The run chart demonstrated stable variation with no special cause signals."},
                        ],
                        "limitations": [
                            "Single site study with limited sample size.",
                            "Unmeasured external factors could influence fall rates.",
                        ],
                        "abstract_draft": "Background: Falls are a critical patient safety issue. Methods: We analyzed monthly falls. Results: Stable rates. Conclusions: Continued monitoring recommended.",
                    })
                )
            )
        ]
    )

    with patch("api.routers.ai.litellm.completion", return_value=mock_llm_reply):
        interp_resp = auth_client.post(f"/ai/interpret-results/{pid}")
        assert interp_resp.status_code == 200, interp_resp.text
        data = interp_resp.json()
        assert len(data["interpretations"]) == 2
        assert len(data["limitations"]) == 2
        assert "Background" in data["abstract_draft"]

    # Verify persistence onto AnalysisRun and Project
    with SessionLocal() as db:
        r1 = db.get(AnalysisRun, run1_id)
        r2 = db.get(AnalysisRun, run2_id)
        assert "averaged 2.0" in json.loads(r1.result_json).get("ai_interpretation", "")
        assert "stable variation" in json.loads(r2.result_json).get("ai_interpretation", "")

        p = db.get(Project, pid)
        plan = json.loads(p.ai_analysis_plan)
        narrative = plan.get("narrative", {})
        assert len(narrative.get("limitations", [])) == 2
        assert "Background" in narrative.get("abstract_draft", "")


def test_resume_and_mentor_view_surface_ai_interpretation_not_placeholder(auth_client):
    _register(auth_client, "interpret_precedence@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Precedence Test", "description": "Testing interpretation precedence"},
        files={"file": ("data.csv", b"month,falls\n2024-01,2\n2024-02,3\n2024-03,1\n", "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["project"]["id"]
    uid = resp.json()["upload"]["id"]

    advance_to_phase(pid, "plan")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.ai_analysis_plan = json.dumps({"confirmed": True})
        u = db.get(Upload, uid)
        u.acknowledged_flags = u.quality_flags
        db.commit()

    plan_payload = {
        "upload_id": uid,
        "analyses": [{"template": "descriptive_summary", "parameters": {"value_cols": ["falls"]}}],
    }
    run_resp = auth_client.post(f"/analyze/run-plan/{pid}", json=plan_payload)
    assert run_resp.status_code == 200, run_resp.text
    run_id = run_resp.json()["runs"][0]["run_id"]

    mock_llm_reply = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "interpretations": [{"run_id": run_id, "text": "REAL AI INTERPRETATION TEXT."}],
                        "limitations": [],
                        "abstract_draft": "Background: falls reduction.",
                    })
                )
            )
        ]
    )
    with patch("api.routers.ai.litellm.completion", return_value=mock_llm_reply):
        interp_resp = auth_client.post(f"/ai/interpret-results/{pid}")
        assert interp_resp.status_code == 200, interp_resp.text

    # Resume must surface the real AI interpretation, not the template's boilerplate placeholder.
    resume = auth_client.get(f"/projects/{pid}/resume").json()
    resumed_run = resume["runs"][0]
    assert resumed_run["ai_interpretation"] == "REAL AI INTERPRETATION TEXT."

    # Mentor view (anonymous) must show the same, not the placeholder either.
    share = auth_client.post(f"/share/{pid}/create", json={}).json()
    anon_client = TestClient(app)
    view = anon_client.get(f"/share/view/{share['token']}").json()
    assert view["results"][0]["interpretation"] == "REAL AI INTERPRETATION TEXT."
    anon_client.close()
