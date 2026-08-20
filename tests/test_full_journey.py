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


def _create_project(client, *, title: str = "Diabetes QI") -> int:
    response = client.post(
        "/projects",
        json={
            "title": title,
            "description": "Improve diabetes outcomes before and after the January 2025 care workflow.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _save_full_intake(client, project_id: int) -> None:
    payload = {
        "answers": {
            "q1": "Increase the percentage of patients with diabetes whose A1c is at goal.",
            "q2": "A percentage or proportion (percent of patients screened)",
            "q3": "Yes — before and after an intervention",
            "q4": "Comparing groups at one point in time",
            "q5": "Monthly",
            "q6": 24,
            "q7": {"description": "Diabetes registry outreach workflow", "date": "2025-01-01"},
            "q8": "Same unit pre vs. post",
            "q9": "All three",
            "q10": {"email": "mentor@example.edu", "deadline": "2026-09-01"},
        }
    }
    response = client.post(f"/intake/{project_id}", json=payload)
    assert response.status_code == 200, response.text


def _dictionary_file():
    return ("dictionary.txt", b"patient_id: sequential study id, not linked to medical record.", "text/plain")


def _upload_csv_fixture(client, project_id: int) -> dict:
    with FIXTURE.open("rb") as fh:
        response = client.post(
            f"/upload/{project_id}",
            files={"file": (FIXTURE.name, fh, "text/csv"), "dictionary": _dictionary_file()},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _run_analysis(client, project_id: int, upload_id: int, template: str, parameters: dict) -> dict:
    response = client.post(
        "/analyze/run",
        json={
            "project_id": project_id,
            "upload_id": upload_id,
            "template": template,
            "parameters": parameters,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_docx_contains_report_package(content: bytes) -> None:
    assert content.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(content)) as docx:
        names = set(docx.namelist())
        assert "word/media/image1.png" in names
        document_xml = docx.read("word/document.xml").decode("utf-8")

    assert "Chi-square" in document_xml
    assert "Limitations" in document_xml
    assert "Audit Trail" in document_xml
    assert "Statistical Code Supplement (R)" in document_xml


def test_real_dataset_resident_journey_and_regression_guards(client):
    assert FIXTURE.exists(), f"Missing real dataset fixture at {FIXTURE}"

    _register_then_login(client)
    project_id = _create_project(client)
    _save_full_intake(client, project_id)

    upload = _upload_csv_fixture(client, project_id)
    assert upload["row_count"] == 600
    upload_id = upload["upload_id"]
    flags = upload["quality_flags"]
    assert any(flag["rule"] == "case_inconsistent" and flag["col"] == "period" for flag in flags)
    assert any(flag["rule"] == "missing_pct" and flag["col"] == "acr_ug_g" for flag in flags)
    assert not any(flag["rule"] == "outlier_count" and flag["col"] == "a1c_at_goal" for flag in flags)

    recommendations = client.get(f"/analyze/{project_id}/recommend")
    assert recommendations.status_code == 200, recommendations.text
    ranked = recommendations.json()
    assert len(ranked) == 3
    assert ranked[0]["template"] == "before_after_pct"

    pct_result = _run_analysis(
        client,
        project_id,
        upload_id,
        "before_after_pct",
        {
            "group_col": "period",
            "outcome_col": "a1c_at_goal",
            "pre_val": "pre",
            "post_val": "post",
        },
    )
    assert "Chi-square" in pct_result["test_used"]
    assert 0.02 < pct_result["p_value"] < 0.04
    assert sum(row["n"] for row in pct_result["table"]) == 557
    assert pct_result["figure_base64"]
    pct_run_id = pct_result["run_id"]

    mean_result = _run_analysis(
        client,
        project_id,
        upload_id,
        "before_after_mean",
        {
            "group_col": "period",
            "value_col": "current_a1c",
            "pre_val": "pre",
            "post_val": "post",
        },
    )
    assert "Wilcoxon" in mean_result["test_used"]
    assert mean_result["p_value"] < 0.01

    p_chart_result = _run_analysis(
        client,
        project_id,
        upload_id,
        "p_chart",
        {
            "date_col": "encounter_date",
            "numerator_col": "a1c_at_goal",
            "intervention_date": "2025-01-01",
        },
    )
    assert isinstance(p_chart_result["ucl"], list)

    docx = client.get(f"/report/{pct_run_id}/docx")
    assert docx.status_code == 200, docx.text
    _assert_docx_contains_report_package(docx.content)

    pdf = client.get(f"/report/{pct_run_id}/pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")

    excel_project_id = _create_project(client, title="Diabetes QI Excel")
    frame = pd.read_csv(FIXTURE)
    excel_raw = io.BytesIO()
    frame.to_excel(excel_raw, index=False)
    excel_raw.seek(0)
    excel_upload = client.post(
        f"/upload/{excel_project_id}",
        files={
            "file": (
                "diabetes_care_qi_full.xlsx",
                excel_raw,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "dictionary": _dictionary_file(),
        },
    )
    assert excel_upload.status_code == 200, excel_upload.text
    excel_result = _run_analysis(
        client,
        excel_project_id,
        excel_upload.json()["upload_id"],
        "before_after_pct",
        {
            "group_col": "period",
            "outcome_col": "a1c_at_goal",
            "pre_val": "pre",
            "post_val": "post",
        },
    )
    assert abs(excel_result["p_value"] - pct_result["p_value"]) <= 1e-6

    share = client.post(f"/share/{project_id}/create", json={})
    assert share.status_code == 200, share.text
    token = share.json()["token"]
    assert token

    with TestClient(app) as anonymous_client:
        mentor_view = anonymous_client.get(f"/share/view/{token}")
        assert mentor_view.status_code == 200, mentor_view.text
        assert mentor_view.json()["figure_base64"]

        comment = anonymous_client.post(
            f"/share/view/{token}/comment",
            json={"author_name": "Dr. Mentor", "text": "Good QI story."},
        )
        assert comment.status_code == 200, comment.text

        protected_projects = anonymous_client.get("/projects")
        assert protected_projects.status_code == 401

        mentor_docx = anonymous_client.get(f"/api/share/view/{token}/report/docx")
        assert mentor_docx.status_code == 404

    prefixed_health = client.get("/api/health")
    assert prefixed_health.status_code == 200, prefixed_health.text
