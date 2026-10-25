import json
import pytest

from api.database import SessionLocal
from api.models_db import AnalysisRun, EditHistory, Project, Upload
from tests.helpers import advance_to_phase


def _register(client, email="run_plan_test@example.com"):
    client.post("/auth/register", json={"email": email, "password": "password123"})


def test_batch_execution_all_ok_and_persistence(auth_client):
    _register(auth_client, "batch_ok@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Batch Test", "description": "Testing batch run plan"},
        files={"file": ("data.csv", b"month,falls,patient_days\n2024-01,2,100\n2024-02,3,110\n2024-03,1,105\n", "text/csv")},
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
        "analyses": [
            {"template": "descriptive_summary", "parameters": {"value_cols": ["falls", "patient_days"]}},
            {"template": "run_chart", "parameters": {"date_col": "month", "value_col": "falls"}},
        ],
    }
    run_resp = auth_client.post(f"/analyze/run-plan/{pid}", json=plan_payload)
    assert run_resp.status_code == 200, run_resp.text
    data = run_resp.json()
    assert len(data["runs"]) == 2
    assert len(data["failures"]) == 0
    assert data["runs"][0]["status"] == "ok"
    assert data["runs"][1]["status"] == "ok"
    assert data["runs"][0]["run_id"] != data["runs"][1]["run_id"]

    with SessionLocal() as db:
        runs = db.query(AnalysisRun).filter_by(project_id=pid).all()
        assert len(runs) == 2
        p = db.get(Project, pid)
        plan = json.loads(p.ai_analysis_plan)
        assert plan["confirmed"] is True
        assert plan["stale"] is False
        assert "executed_at" in plan


def test_stale_plan_is_rejected_even_if_confirmed(auth_client):
    _register(auth_client, "stale_run@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Stale Plan Test", "description": "Testing stale plan rejection"},
        files={"file": ("data.csv", b"month,falls,patient_days\n2024-01,2,100\n2024-02,3,110\n2024-03,1,105\n", "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["project"]["id"]
    uid = resp.json()["upload"]["id"]

    advance_to_phase(pid, "plan")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.ai_analysis_plan = json.dumps({"confirmed": True, "stale": True})
        u = db.get(Upload, uid)
        u.acknowledged_flags = u.quality_flags
        db.commit()

    plan_payload = {
        "upload_id": uid,
        "analyses": [
            {"template": "descriptive_summary", "parameters": {"value_cols": ["falls", "patient_days"]}},
        ],
    }
    run_resp = auth_client.post(f"/analyze/run-plan/{pid}", json=plan_payload)
    assert run_resp.status_code == 409
    data = run_resp.json()
    assert "stale" in data["error"]["message"].lower()

    with SessionLocal() as db:
        assert db.query(AnalysisRun).filter_by(project_id=pid).count() == 0


def test_one_item_failure_does_not_abort_batch(auth_client):
    _register(auth_client, "batch_partial@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Partial Test", "description": "Testing partial failure"},
        files={"file": ("data.csv", b"month,falls,patient_days\n2024-01,2,100\n2024-02,3,110\n", "text/csv")},
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
        "analyses": [
            {"template": "descriptive_summary", "parameters": {"value_cols": ["falls"]}},
            {"template": "run_chart", "parameters": {"date_col": "nonexistent_col", "value_col": "falls"}},
        ],
    }
    run_resp = auth_client.post(f"/analyze/run-plan/{pid}", json=plan_payload)
    assert run_resp.status_code == 200, run_resp.text
    data = run_resp.json()
    assert len(data["runs"]) == 1
    assert data["runs"][0]["status"] == "ok"
    assert len(data["failures"]) == 1
    assert data["failures"][0]["status"] == "error"
    assert data["failures"][0]["template"] == "run_chart"


def test_rerun_replaces_prior_runs_and_preserves_edits(auth_client):
    _register(auth_client, "batch_edits@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Rerun Test", "description": "Testing edit preservation"},
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
        "analyses": [
            {"template": "descriptive_summary", "parameters": {"value_cols": ["falls"]}},
            {"template": "run_chart", "parameters": {"date_col": "month", "value_col": "falls"}},
        ],
    }
    # Initial execution
    run_resp1 = auth_client.post(f"/analyze/run-plan/{pid}", json=plan_payload)
    assert run_resp1.status_code == 200
    runs1 = run_resp1.json()["runs"]
    descriptive_run_id = runs1[0]["run_id"]

    # Save an edit on the descriptive run
    edit_resp = auth_client.post(
        f"/projects/{pid}/edits",
        json={
            "field": "caption",
            "run_id": descriptive_run_id,
            "original_text": "Original caption",
            "edited_text": "Resident's custom edited caption",
        },
    )
    assert edit_resp.status_code == 200

    # Rerun the plan
    run_resp2 = auth_client.post(f"/analyze/run-plan/{pid}", json=plan_payload)
    assert run_resp2.status_code == 200
    runs2 = run_resp2.json()["runs"]
    new_descriptive_run_id = runs2[0]["run_id"]

    # Exactly 2 runs exist in DB (replaced, not accumulated)
    with SessionLocal() as db:
        db_runs = db.query(AnalysisRun).filter_by(project_id=pid).all()
        assert len(db_runs) == 2

        # Edit preserved and attached to the new run of the same template
        edits = db.query(EditHistory).filter_by(run_id=new_descriptive_run_id).all()
        assert len(edits) == 1
        assert edits[0].field == "caption"
        assert edits[0].edited_text == "Resident's custom edited caption"


@pytest.mark.parametrize("reviewed,start", [(True, "No denominator was assigned. The resident reviewed this flag"),
                                            (False, "No denominator was assigned, so")])
def test_run_plan_wording_follows_the_review_flag(auth_client, reviewed, start):
    _register(auth_client, "reviewed_%s@example.com" % reviewed)
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Review Flag", "description": "Testing the review flag wording"},
        files={"file": ("data.csv", b"month,falls,patient_days\n" + b"".join(
            b"2024-%02d,%d,100\n" % (m, 2 + m % 3) for m in range(1, 13)), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid, uid = resp.json()["project"]["id"], resp.json()["upload"]["id"]
    advance_to_phase(pid, "plan")
    item = {"template": "u_c_chart", "parameters": {"date_col": "month", "count_col": "falls"}}
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.ai_project_design = json.dumps({"primary_outcome": {"label": "Falls", "column": "falls", "kind": "rate"}})
        p.ai_analysis_plan = json.dumps({"confirmed": True, "analyses": [dict(item, flag_reviewed=reviewed)]})
        u = db.get(Upload, uid)
        u.acknowledged_flags = u.quality_flags
        db.commit()
    r = auth_client.post(f"/analyze/run-plan/{pid}", json={"upload_id": uid, "analyses": [item]})
    assert r.status_code == 200, r.text
    runs = r.json()["runs"]
    assert runs, r.json()
    assert runs[0]["limitations"][0].startswith(start)


def test_overlapping_run_plan_requests_keep_one_set_of_runs(auth_client):
    from concurrent.futures import ThreadPoolExecutor

    _register(auth_client, "overlap_run@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Overlap", "description": "Two requests at once must not double the runs"},
        files={"file": ("data.csv", b"month,falls,patient_days\n2024-01,2,100\n2024-02,3,110\n2024-03,1,105\n", "text/csv")},
    )
    pid, uid = resp.json()["project"]["id"], resp.json()["upload"]["id"]
    advance_to_phase(pid, "plan")
    with SessionLocal() as db:
        db.get(Project, pid).ai_analysis_plan = json.dumps({"confirmed": True})
        u = db.get(Upload, uid)
        u.acknowledged_flags = u.quality_flags
        db.commit()
    payload = {"upload_id": uid, "analyses": [
        {"template": "descriptive_summary", "parameters": {"value_cols": ["falls"]}},
        {"template": "run_chart", "parameters": {"date_col": "month", "value_col": "falls"}},
    ]}
    with ThreadPoolExecutor(2) as pool:
        codes = [f.result().status_code for f in [pool.submit(auth_client.post, f"/analyze/run-plan/{pid}", json=payload) for _ in range(2)]]
    assert codes == [200, 200]
    with SessionLocal() as db:
        assert db.query(AnalysisRun).filter_by(project_id=pid).count() == 2


def test_daily_granularity_is_coarsened_for_a_yes_no_outcome_at_validation(auth_client):
    _register(auth_client, "freq_default@example.com")
    rows = "".join(f"2024-{1 + i // 28:02d}-{1 + i % 28:02d},{i % 2}\n" for i in range(112))
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Freq", "description": "Daily dates with a yes/no outcome must not become daily charts"},
        files={"file": ("data.csv", ("visit_date,at_goal\n" + rows).encode(), "text/csv")},
    )
    pid = resp.json()["project"]["id"]
    with SessionLocal() as db:
        db.get(Project, pid).ai_project_design = json.dumps({
            "primary_outcome": {"label": "At goal", "column": "at_goal", "kind": "binary"},
            "time_structure": {"has_dates": True, "date_column": "visit_date", "granularity": "day"},
        })
        db.commit()
        from api.routers.analyze import check_plan_item
        import pandas as pd
        df = pd.read_csv(__import__("io").BytesIO(("visit_date,at_goal\n" + rows).encode()))
        checked = check_plan_item(db, db.get(Project, pid), None, df, "p_chart", {"date_col": "visit_date", "numerator_col": "at_goal"})
    assert checked["parameters"]["freq"] == "ME"
