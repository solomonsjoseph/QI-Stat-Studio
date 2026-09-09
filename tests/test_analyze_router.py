"""Integration tests for /analyze/run and /analyze/{id}/recommend."""
import json
import os
import pathlib
import tempfile

import numpy as np
import pandas as pd

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from api.config import settings
from api.database import SessionLocal
from api.models_db import AnalysisRun, FailureLog, Project, Upload


def _project(client, title="Analyze Test"):
    response = client.post("/projects", json={"title": title, "description": "test"})
    assert response.status_code == 200, response.text
    pid = response.json()["id"]
    from tests.helpers import advance_to_phase
    advance_to_phase(pid, "plan")
    return pid


def _make_encrypted_csv(client, n=18):
    """Create an encrypted CSV for an owned project and return (project_id, upload_id)."""
    dates = pd.date_range("2023-01-01", periods=n, freq="ME")
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "encounter_date": dates.strftime("%Y-%m-%d"),
        "hba1c": rng.uniform(6.5, 10.0, n),
        "outcome": rng.integers(0, 2, n).astype(int),
        "period": ["pre"] * (n // 2) + ["post"] * (n - n // 2),
    })
    csv_bytes = df.to_csv(index=False).encode()
    enc_bytes = settings.fernet.encrypt(csv_bytes)

    pid = _project(client)
    enc_path = pathlib.Path(tempfile.mktemp(suffix=".enc"))
    enc_path.write_bytes(enc_bytes)

    with SessionLocal() as db:
        u = Upload(
            project_id=pid,
            filename="test.csv",
            original_filename="test.csv",
            file_type="csv",
            size_bytes=len(csv_bytes),
            checksum_sha256="test",
            storage_key=enc_path.name,
            status="active",
            encrypted_path=str(enc_path),
            col_types=json.dumps({c: "Number" for c in df.columns}),
            column_map=json.dumps({}),
            quality_flags="[]",
        )
        db.add(u)
        db.commit()
        uid = u.id
    from tests.helpers import advance_to_phase
    advance_to_phase(pid, "plan")
    return pid, uid


def test_run_descriptive_returns_run_id(auth_client):
    pid, uid = _make_encrypted_csv(auth_client)
    resp = auth_client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "descriptive_summary",
        "parameters": {"value_cols": ["hba1c"], "group_col": "period"},
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "run_id" in data
    assert data["run_id"] > 0


def test_all_code_supplements_always_generated(auth_client):
    pid, uid = _make_encrypted_csv(auth_client)
    resp = auth_client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "descriptive_summary",
        "parameters": {"value_cols": ["hba1c"], "group_col": "period"},
    })
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        run = db.query(AnalysisRun).filter_by(project_id=pid).order_by(AnalysisRun.id.desc()).first()
        assert run.code_r
        assert run.code_spss
        assert run.code_sas

def test_run_run_chart_returns_figure(auth_client):
    pid, uid = _make_encrypted_csv(auth_client)
    resp = auth_client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "run_chart",
        "parameters": {"date_col": "encounter_date", "value_col": "hba1c"},
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["figure_base64"] is not None
    assert "result_summary" in data



def test_template_execution_failure_records_failure_log(auth_client, monkeypatch):
    from api.templates import registry

    pid, uid = _make_encrypted_csv(auth_client)

    def fail_template(df, params):
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setitem(registry.TEMPLATE_REGISTRY, "run_chart", fail_template)
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        no_raise_client.cookies.update(auth_client.cookies)
        resp = no_raise_client.post("/analyze/run", json={
            "project_id": pid,
            "upload_id": uid,
            "template": "run_chart",
            "parameters": {"date_col": "encounter_date", "value_col": "hba1c"},
        })

    assert resp.status_code == 500
    with SessionLocal() as db:
        assert db.query(FailureLog).count() == 1
        row = db.query(FailureLog).filter_by(project_id=pid, upload_id=uid).one()
        assert row.template == "run_chart"
        assert row.error_type == "RuntimeError"
        assert row.action == "analysis_run"
        assert row.message == "Analysis failed"

def test_run_before_after_mean(auth_client):
    pid, uid = _make_encrypted_csv(auth_client)
    resp = auth_client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "before_after_mean",
        "parameters": {"group_col": "period", "value_col": "hba1c", "pre_val": "pre", "post_val": "post"},
    })
    assert resp.status_code == 200, resp.text
    assert "p_value" in resp.json()


def test_run_unknown_template_returns_400(auth_client):
    pid, uid = _make_encrypted_csv(auth_client)
    resp = auth_client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "no_such_template",
        "parameters": {},
    })
    assert resp.status_code == 400


def test_run_bad_upload_id_returns_404(auth_client):
    pid = _project(auth_client, "Bad Upload")
    resp = auth_client.post("/analyze/run", json={
        "project_id": pid, "upload_id": 99999,
        "template": "run_chart",
        "parameters": {"date_col": "encounter_date", "value_col": "hba1c"},
    })
    assert resp.status_code == 404


def test_run_blocks_when_outcome_column_over_30pct_missing(auth_client):
    """POST /analyze/run returns 400 when chosen outcome col is >30% missing."""
    n = 20
    dates = pd.date_range("2023-01-01", periods=n, freq="ME")
    rng = np.random.default_rng(1)
    outcome = rng.integers(0, 2, n).astype(float)
    outcome[:16] = float("nan")
    df = pd.DataFrame({
        "encounter_date": dates.strftime("%Y-%m-%d"),
        "hba1c": rng.uniform(6.5, 10.0, n),
        "outcome": outcome,
        "period": ["pre"] * (n // 2) + ["post"] * (n - n // 2),
    })
    csv_bytes = df.to_csv(index=False).encode()
    enc_path = pathlib.Path(tempfile.mktemp(suffix=".enc"))
    enc_path.write_bytes(settings.fernet.encrypt(csv_bytes))
    pid = _project(auth_client, "Missing Test")

    with SessionLocal() as db:
        u = Upload(
            project_id=pid,
            filename="missing.csv",
            original_filename="missing.csv",
            file_type="csv",
            size_bytes=len(csv_bytes),
            checksum_sha256="test",
            storage_key=enc_path.name,
            status="active",
            encrypted_path=str(enc_path),
            col_types=json.dumps({c: "Number" for c in df.columns}),
            column_map=json.dumps({}),
            quality_flags="[]",
        )
        db.add(u)
        db.commit()
        uid = u.id

    resp = auth_client.post("/analyze/run", json={
        "project_id": pid,
        "upload_id": uid,
        "template": "before_after_pct",
        "parameters": {"group_col": "period", "outcome_col": "outcome", "pre_val": "pre", "post_val": "post"},
    })
    assert resp.status_code == 400
    assert "missing" in resp.json()["error"]["message"].lower()


def test_freq_derives_from_design_granularity(auth_client):
    from api.routers.analyze import _granularity_to_freq
    assert _granularity_to_freq("day") == "D"
    assert _granularity_to_freq("week") == "W"
    assert _granularity_to_freq("month") == "ME"
    assert _granularity_to_freq("quarter") == "QE"
    assert _granularity_to_freq("unknown") == "ME"
    assert _granularity_to_freq(None) == "ME"
