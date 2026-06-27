"""Tests for /report/{id}/docx and /report/{id}/pdf endpoints."""
import json, os
os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from fastapi.testclient import TestClient
from api.main import app
from api.database import engine, Base, SessionLocal
from api.models_db import Project, AnalysisRun

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _seed_run(template="run_chart", with_figure=False):
    db = SessionLocal()
    p = Project(title="Test Project", description="test")
    db.add(p); db.flush()
    result = {"methods": "A run chart was used.", "result_summary": "Median=5.0", "figure_base64": None}
    run = AnalysisRun(
        project_id=p.id, template=template,
        parameters=json.dumps({"date_col": "encounter_date", "value_col": "hba1c"}),
        result_json=json.dumps(result), code_r="# R code here",
    )
    db.add(run); db.commit()
    run_id = run.id
    db.close()
    return run_id


def test_docx_returns_bytes():
    rid = _seed_run()
    resp = client.get(f"/report/{rid}/docx")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert len(resp.content) > 1000  # non-empty Word doc


def test_pdf_returns_bytes():
    rid = _seed_run()
    resp = client.get(f"/report/{rid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_report_404():
    resp = client.get("/report/99999/docx")
    assert resp.status_code == 404
