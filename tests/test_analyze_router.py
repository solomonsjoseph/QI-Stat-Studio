"""Integration tests for /analyze/run and /analyze/{id}/recommend."""
import io, json, os
import pandas as pd
import numpy as np

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from fastapi.testclient import TestClient
from api.main import app
from api.database import engine, Base, SessionLocal
from api.models_db import Project, Upload
from api.config import settings

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _make_encrypted_csv(n=18):
    """Create an encrypted CSV and return (project_id, upload_id)."""
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

    db = SessionLocal()
    p = Project(title="Analyze Test", description="test")
    db.add(p); db.flush()

    import tempfile, pathlib
    enc_path = pathlib.Path(tempfile.mktemp(suffix=".enc"))
    enc_path.write_bytes(enc_bytes)

    u = Upload(
        project_id=p.id, filename="test.csv",
        encrypted_path=str(enc_path),
        col_types=json.dumps({c: "Number" for c in df.columns}),
        quality_flags="[]",
    )
    db.add(u); db.commit()
    pid, uid = p.id, u.id
    db.close()
    return pid, uid


def test_run_descriptive_returns_run_id():
    pid, uid = _make_encrypted_csv()
    resp = client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "descriptive_summary",
        "parameters": {"value_cols": ["hba1c"], "group_col": "period"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["run_id"] > 0


def test_run_run_chart_returns_figure():
    pid, uid = _make_encrypted_csv()
    resp = client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "run_chart",
        "parameters": {"date_col": "encounter_date", "value_col": "hba1c"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["figure_base64"] is not None
    assert "result_summary" in data


def test_run_before_after_mean():
    pid, uid = _make_encrypted_csv()
    resp = client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "before_after_mean",
        "parameters": {"group_col": "period", "value_col": "hba1c",
                       "pre_val": "pre", "post_val": "post"},
    })
    assert resp.status_code == 200
    assert "p_value" in resp.json()


def test_run_unknown_template_returns_400():
    pid, uid = _make_encrypted_csv()
    resp = client.post("/analyze/run", json={
        "project_id": pid, "upload_id": uid,
        "template": "no_such_template",
        "parameters": {},
    })
    assert resp.status_code == 400


def test_run_bad_upload_id_returns_404():
    resp = client.post("/analyze/run", json={
        "project_id": 1, "upload_id": 99999,
        "template": "run_chart",
        "parameters": {"date_col": "encounter_date", "value_col": "hba1c"},
    })
    assert resp.status_code == 404


def test_recommend_returns_ordered_list():
    """GET /analyze/{project_id}/recommend returns ordered template list."""
    # Seed project + intake answers
    db = SessionLocal()
    p = Project(title="Rec Test", description="x")
    db.add(p); db.flush()
    from api.models_db import IntakeAnswer
    db.add(IntakeAnswer(project_id=p.id, question_key="q2", answer="A percentage or proportion"))
    db.add(IntakeAnswer(project_id=p.id, question_key="q3", answer="No — I'm just describing one time period"))
    db.add(IntakeAnswer(project_id=p.id, question_key="q4", answer="Comparing groups at one time point"))
    db.add(IntakeAnswer(project_id=p.id, question_key="q6", answer="12"))
    db.commit(); pid = p.id; db.close()

    resp = client.get(f"/analyze/{pid}/recommend")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3
    # First item must be marked recommended
    assert items[0]["recommended"] is True
    # First template should be descriptive_summary (no comparison + groups)
    assert items[0]["template"] == "descriptive_summary"
