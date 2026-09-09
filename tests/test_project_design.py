import json

import pandas as pd
import pytest

from api.database import SessionLocal
from api.dataset_profile import build_profile
from api.models_api import OutcomeDesign, ProjectDesign
from api.models_db import Project, Upload
from api.project_design import merge_ai_design, merge_user_design, validate_design_columns
from api.routers.ai import _drop_irrelevant_questions
from api.routers.upload import detect_col_type


def _register(client, email="design_test@example.com"):
    client.post("/auth/register", json={"email": email, "password": "password123"})


def _fixture_profile(name: str):
    df = pd.read_csv(f"tests/fixtures/{name}.csv")
    col_types = {column: detect_col_type(column, df[column]) for column in df.columns}
    return df, build_profile(df, col_types)


def test_put_design_rejects_column_absent_from_upload(auth_client):
    _register(auth_client, "design_col@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Design Col Test", "description": "desc"},
        files={"file": ("data.csv", b"col_a,col_b\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["project"]["id"]

    design_payload = {
        "aim": "Improve quality",
        "primary_outcome": {
            "label": "Nonexistent outcome",
            "column": "totally_missing_col",
            "kind": "continuous",
        },
    }
    put_resp = auth_client.put(f"/projects/{pid}/design", json=design_payload)
    assert put_resp.status_code == 422
    assert "primary_outcome.column" in put_resp.json()["error"]["field_errors"]


def test_put_design_accepts_valid_columns_and_marks_user_confirmed(auth_client):
    _register(auth_client, "design_ok@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Design OK Test", "description": "desc"},
        files={"file": ("data.csv", b"col_a,col_b\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["project"]["id"]

    design_payload = {
        "aim": "Improve quality",
        "primary_outcome": {
            "label": "Outcome A",
            "column": "col_a",
            "kind": "continuous",
        },
    }
    put_resp = auth_client.put(f"/projects/{pid}/design", json=design_payload)
    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    design = body["ai_project_design"]
    assert design["status"]["aim"] == "user-confirmed"
    assert design["status"]["primary_outcome.column"] == "user-confirmed"


def test_user_corrected_field_survives_later_ai_turn():
    old_design = {
        "aim": "Original Aim",
        "primary_outcome": {"label": "Outcome A", "column": "col_a", "kind": "continuous"},
        "status": {
            "aim": "user-corrected",
            "primary_outcome.column": "user-corrected",
        },
    }

    # Model returns a different column for primary_outcome
    ai_incoming = ProjectDesign(
        aim="AI suggested new aim",
        primary_outcome=OutcomeDesign(label="AI Outcome", column="col_b", kind="continuous"),
    )

    merged = merge_ai_design(ai_incoming, old_design)
    assert merged.status["primary_outcome.column"] == "user-corrected"
    assert merged.primary_outcome.column == "col_a"  # Preserved user choice!
    assert merged.status["aim"] == "user-corrected"
    assert merged.aim == "Original Aim"


def test_vague_fixture_exposes_multiple_ambiguous_numeric_outcomes():
    _, profile = _fixture_profile("vague_no_outcome")

    assert profile["candidate_roles"]["outcome"] == ["count_a", "count_b"]
    inferred_types = {column["name"]: column["inferred_type"] for column in profile["columns"]}
    assert inferred_types["count_a"] == "Number"
    assert inferred_types["count_b"] == "Number"


def test_descriptive_fixture_has_no_intervention_date_and_strips_question():
    _, profile = _fixture_profile("descriptive_no_intervention")

    assert profile["candidate_roles"]["date"] == ["month"]
    assert not any("intervention" in column.lower() for column in profile["candidate_roles"]["date"])
    design = ProjectDesign(intervention={"present": False})
    assert _drop_irrelevant_questions(
        "What outcome are you measuring?\nWhen is the intervention date?",
        design,
    ) == "What outcome are you measuring?"
