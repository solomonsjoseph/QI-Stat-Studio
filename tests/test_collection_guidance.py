import json
from unittest.mock import patch

import pandas as pd
import pytest

from api.collection_guidance import deterministic_recommendations
from api.database import SessionLocal
from api.models_api import OutcomeDesign, ProjectDesign
from api.models_db import Project, Upload


def _load_fixture(name: str) -> pd.DataFrame:
    return pd.read_csv(f"tests/fixtures/{name}.csv")


def _register(client, email="guidance_test@example.com"):
    client.post("/auth/register", json={"email": email, "password": "password123"})


def test_each_rule_fires_on_crafted_design_and_frame():
    # 1. missing denominator
    design_prop = ProjectDesign(
        aim="Reduce infections",
        primary_outcome=OutcomeDesign(label="Infection rate", column="infections", kind="proportion"),
    )
    df_missing_denom = pd.DataFrame({"infections": [1, 2, 3]})
    recs = deterministic_recommendations(design_prop, df_missing_denom, {})
    rec_ids = {r["id"] for r in recs}
    assert "missing-denominator" in rec_ids

    # 2. post-only
    design_post_only = ProjectDesign(
        aim="Check intervention",
        comparison="pre-post",
        intervention={"present": True, "start_date": "2024-01-01"},
        time_structure={"has_dates": True, "date_column": "dt"},
        primary_outcome=OutcomeDesign(label="val", column="val", kind="continuous"),
    )
    df_post_only = pd.DataFrame({
        "dt": ["2024-02-01", "2024-03-01", "2024-04-01"],
        "val": [10, 20, 30],
    })
    recs = deterministic_recommendations(design_post_only, df_post_only, {})
    rec_ids = {r["id"] for r in recs}
    assert "post-only" in rec_ids

    # 3. no-time-column
    design_ts = ProjectDesign(
        aim="Trend over time",
        comparison="time-series",
        time_structure={"has_dates": False},
        primary_outcome=OutcomeDesign(label="val", column="val", kind="continuous"),
    )
    df_ts = pd.DataFrame({"val": [1, 2, 3]})
    recs = deterministic_recommendations(design_ts, df_ts, {})
    rec_ids = {r["id"] for r in recs}
    assert "no-time-column" in rec_ids

    # 4. no-pairing-key
    design_paired = ProjectDesign(
        aim="Paired study",
        paired=True,
        pairing_id_column="missing_id",
        primary_outcome=OutcomeDesign(label="val", column="val", kind="continuous"),
    )
    recs = deterministic_recommendations(design_paired, df_ts, {})
    rec_ids = {r["id"] for r in recs}
    assert "no-pairing-key" in rec_ids

    # 5. no-balancing-measure
    assert "no-balancing-measure" in rec_ids


def test_endpoint_returns_200_with_rule_only_output_when_llm_raises(auth_client):
    _register(auth_client, "guidance_err@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "Guidance Test", "description": "desc"},
        files={"file": ("data.csv", b"month,infections\n2024-01,2\n2024-02,3\n", "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["project"]["id"]

    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.ai_project_design = json.dumps({
            "aim": "Reduce infections",
            "primary_outcome": {"label": "Infection rate", "column": "infections", "kind": "proportion"},
        })
        db.commit()

    # Simulate LLM raising an exception
    with patch("api.routers.ai.litellm.completion", side_effect=RuntimeError("AI explosion")):
        guidance_resp = auth_client.post(f"/ai/collection-guidance/{pid}")
        assert guidance_resp.status_code == 200, guidance_resp.text
        data = guidance_resp.json()
        assert "recommendations" in data
        rec_ids = {r["id"] for r in data["recommendations"]}
        assert "missing-denominator" in rec_ids
        assert all(r["source"] == "rule" for r in data["recommendations"])

        with SessionLocal() as db:
            p = db.get(Project, pid)
            assert p.data_collection_notes is not None
            saved = json.loads(p.data_collection_notes)
            assert "recommendations" in saved


def test_post_only_rule_fires_for_file_fixture():
    design = ProjectDesign(
        aim="Check intervention",
        comparison="pre-post",
        intervention={"present": True, "start_date": "2024-12-01"},
        time_structure={"has_dates": True, "date_column": "period_date"},
        primary_outcome=OutcomeDesign(label="Falls", column="falls", kind="continuous"),
    )

    rec_ids = {
        rec["id"]
        for rec in deterministic_recommendations(design, _load_fixture("post_only"), {})
    }

    assert "post-only" in rec_ids


def test_missing_denominator_rule_fires_for_file_fixture():
    design = ProjectDesign(
        aim="Reduce infections",
        primary_outcome=OutcomeDesign(
            label="Infection rate",
            column="infections",
            kind="proportion",
        ),
    )

    rec_ids = {
        rec["id"]
        for rec in deterministic_recommendations(design, _load_fixture("missing_denominator"), {})
    }

    assert "missing-denominator" in rec_ids
