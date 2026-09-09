from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from api.main import app


PASSWORD = "password123"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "diabetes_care_qi_full.csv"


def _register_then_login(client, email: str = "journey@example.com") -> None:
    registered = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 200, registered.text

    logged_out = client.post("/auth/logout")
    assert logged_out.status_code == 200, logged_out.text

    logged_in = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged_in.status_code == 200, logged_in.text


def _clarify_turn(*, message: str, confirmed: bool = False) -> dict:
    return {
        "message": message,
        "reasoning": "The description and dataset identify a pre/post diabetes quality-improvement project.",
        "confirmed": confirmed,
        "sufficient_to_continue": True,
        "design": {
            "aim": "Increase the percentage of patients with diabetes whose A1c is at goal",
            "population": "Patients with diabetes in the clinic registry",
            "intervention": {
                "present": True,
                "description": "Diabetes registry outreach workflow",
                "start_date": "2025-01-01",
            },
            "primary_outcome": {
                "label": "A1c at goal",
                "column": "a1c_at_goal",
                "kind": "proportion",
            },
            "comparison": "pre-post",
            "time_structure": {"has_dates": True, "date_column": "encounter_date", "granularity": "month"},
            "group_column": "period",
            "pre_label": "pre",
            "post_label": "post",
            "plain_restatement": "You are evaluating whether registry outreach improved the percentage of diabetes patients at A1c goal.",
            "sufficient_to_continue": True,
        },
    }


def _assert_docx_contains_report_package(content: bytes) -> None:
    assert content.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(content)) as docx:
        names = set(docx.namelist())
        assert "word/document.xml" in names
        document_xml = docx.read("word/document.xml").decode("utf-8")

    assert "Statistical Code Supplement" in document_xml


def test_real_dataset_resident_journey_and_regression_guards(client, mock_llm):
    assert FIXTURE.exists(), f"Missing real dataset fixture at {FIXTURE}"
    _register_then_login(client)

    with FIXTURE.open("rb") as fh:
        intake = client.post(
            "/projects/intake",
            data={
                "title": "Diabetes A1c QI",
                "description": "Improve the percentage of clinic patients with diabetes whose A1c is at goal through registry outreach.",
            },
            files={"file": (FIXTURE.name, fh, "text/csv")},
        )
    assert intake.status_code == 200, intake.text
    intake_data = intake.json()
    project_id = intake_data["project"]["id"]
    upload = intake_data["upload"]
    upload_id = upload["id"]
    assert upload["dataset_profile"]["row_count"] == 600
    assert upload["col_types"]
    assert any(flag["rule"] == "case_inconsistent" and flag["col"] == "period" for flag in upload["quality_flags"])
    assert any(flag["rule"] == "missing_pct" and flag["col"] == "acr_ug_g" for flag in upload["quality_flags"])
    assert not any(flag["rule"] == "outlier_count" and flag["col"] == "a1c_at_goal" for flag in upload["quality_flags"])

    mock_llm.push(_clarify_turn(message="I understand the proposed diabetes A1c quality-improvement project. Which period is before the outreach workflow?"))
    clarify_opening = client.post(f"/ai/clarify/{project_id}", json={"message": None})
    assert clarify_opening.status_code == 200, clarify_opening.text
    assert clarify_opening.json()["confirmed"] is False

    mock_llm.push(_clarify_turn(message="The dataset's period values are pre and post, so I can compare them."))
    clarify_follow_up = client.post(f"/ai/clarify/{project_id}", json={"message": "The pre and post values in period are the comparison periods."})
    assert clarify_follow_up.status_code == 200, clarify_follow_up.text

    clarification = client.post(f"/ai/clarify/{project_id}", json={"confirm": True})
    assert clarification.status_code == 200, clarification.text
    assert clarification.json()["confirmed"] is True

    guidance = client.post(f"/ai/collection-guidance/{project_id}")
    assert guidance.status_code == 200, guidance.text
    assert "recommendations" in guidance.json()

    acknowledge = client.patch(
        f"/upload/{upload_id}/acknowledged-flags",
        json={"flags": upload["quality_flags"]},
    )
    assert acknowledge.status_code == 200, acknowledge.text
    assert acknowledge.json() == {"ok": True}

    analyses = [
        {
            "id": "descriptive-a1c-goal",
            "template": "descriptive_summary",
            "display_name": "A1c-at-goal summary",
            "question": "What proportion of patients are at A1c goal?",
            "rationale": "Summarizes the primary quality measure.",
            "parameters": {"value_cols": ["a1c_at_goal"]},
        },
        {
            "id": "pre-post-a1c-goal",
            "template": "before_after_pct",
            "display_name": "Pre/post A1c-at-goal comparison",
            "question": "Did the percentage at A1c goal differ between pre and post periods?",
            "rationale": "Tests the prespecified pre/post quality-improvement comparison.",
            "parameters": {
                "group_col": "period",
                "outcome_col": "a1c_at_goal",
                "pre_val": "pre",
                "post_val": "post",
            },
        },
    ]
    confirm_plan = client.post(
        f"/ai/recommend-plan/{project_id}",
        json={"confirm": True, "analyses": analyses},
    )
    assert confirm_plan.status_code == 200, confirm_plan.text
    assert confirm_plan.json()["confirmed"] is True

    validation = client.post(
        f"/analyze/validate-plan/{project_id}",
        json={"upload_id": upload_id, "analyses": analyses},
    )
    assert validation.status_code == 200, validation.text
    assert len(validation.json()["items"]) == 2
    assert all(item["ok"] for item in validation.json()["items"])

    run_plan = client.post(
        f"/analyze/run-plan/{project_id}",
        json={"upload_id": upload_id, "analyses": analyses},
    )
    assert run_plan.status_code == 200, run_plan.text
    run_data = run_plan.json()
    assert run_data["failures"] == []
    assert len(run_data["runs"]) == 2
    assert all(run["status"] == "ok" for run in run_data["runs"])
    run_ids = [run["run_id"] for run in run_data["runs"]]
    assert len(set(run_ids)) == 2

    mock_llm.push(
        {
            "interpretations": [
                {"run_id": run_ids[0], "text": "The descriptive summary reports the A1c-at-goal measure across the project population."},
                {"run_id": run_ids[1], "text": "The pre/post comparison estimates whether the observed A1c-at-goal percentages differ between periods."},
            ],
            "limitations": ["This single-site quality-improvement project was not randomized."],
            "abstract_draft": "We evaluated registry outreach and the percentage of patients with diabetes at A1c goal.",
        }
    )
    interpreted = client.post(f"/ai/interpret-results/{project_id}")
    assert interpreted.status_code == 200, interpreted.text
    assert {item["run_id"] for item in interpreted.json()["interpretations"]} == set(run_ids)

    edited_title = "Edited Diabetes A1c QI"
    edited_caption = "Resident-reviewed caption for the A1c summary."
    edited_interpretation = "Resident-reviewed interpretation of the pre/post comparison."
    title_edit = client.post(
        f"/projects/{project_id}/edits",
        json={"field": "title", "original_text": "Diabetes A1c QI", "edited_text": edited_title},
    )
    assert title_edit.status_code == 200, title_edit.text
    caption_edit = client.post(
        f"/projects/{project_id}/edits",
        json={"field": "caption", "run_id": run_ids[0], "original_text": "", "edited_text": edited_caption},
    )
    assert caption_edit.status_code == 200, caption_edit.text
    interpretation_edit = client.post(
        f"/projects/{project_id}/edits",
        json={"field": "interpretation", "run_id": run_ids[1], "original_text": "", "edited_text": edited_interpretation},
    )
    assert interpretation_edit.status_code == 200, interpretation_edit.text

    docx = client.get(f"/report/project/{project_id}/docx")
    assert docx.status_code == 200, docx.text
    _assert_docx_contains_report_package(docx.content)
    pdf = client.get(f"/report/project/{project_id}/pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")

    share = client.post(f"/share/{project_id}/create", json={})
    assert share.status_code == 200, share.text
    token = share.json()["token"]
    assert token

    with TestClient(app) as anonymous_client:
        mentor_view = anonymous_client.get(f"/share/view/{token}")
        assert mentor_view.status_code == 200, mentor_view.text
        package = mentor_view.json()
        assert package["project"]["title"] == edited_title
        assert len(package["results"]) == 2
        by_run_id = {result["run_id"]: result for result in package["results"]}
        assert edited_caption in by_run_id[run_ids[0]]["caption"]
        assert by_run_id[run_ids[1]]["interpretation"] == edited_interpretation

        protected_projects = anonymous_client.get("/projects")
        assert protected_projects.status_code == 401

    frame = pd.read_csv(FIXTURE).head(24)
    excel_raw = io.BytesIO()
    frame.to_excel(excel_raw, index=False)
    excel_intake = client.post(
        "/projects/intake",
        data={
            "title": "Diabetes A1c QI Excel",
            "description": "Use a spreadsheet subset to verify that Excel uploads share the unified intake path.",
        },
        files={
            "file": (
                "diabetes_care_qi_subset.xlsx",
                excel_raw.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert excel_intake.status_code == 200, excel_intake.text
    excel_upload = excel_intake.json()["upload"]
    assert excel_upload["dataset_profile"]["row_count"] == len(frame)
    assert excel_upload["col_types"]

    prefixed_health = client.get("/api/health")
    assert prefixed_health.status_code == 200, prefixed_health.text
