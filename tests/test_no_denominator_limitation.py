import json

import pandas as pd

from api.database import SessionLocal
from api.models_db import Project, Upload
from api.routers.analyze import NO_DENOMINATOR_LIMITATION, execute_template


def _run(params, kind="rate"):
    db = SessionLocal()
    design = {"primary_outcome": {"label": "Falls", "column": "falls", "kind": kind}}
    project = Project(title="p", description="d", deadline="2030-01-01", ai_project_design=json.dumps(design))
    db.add(project)
    db.flush()
    upload = Upload(project_id=project.id, filename="a.csv", original_filename="a.csv", encrypted_path="/tmp/a.enc")
    db.add(upload)
    db.flush()
    df = pd.DataFrame({
        "month": pd.date_range("2023-01-01", periods=12, freq="MS"),
        "falls": [2, 3, 4, 2, 3, 5, 2, 3, 4, 2, 3, 4],
        "patient_days": [1000 + i * 10 for i in range(12)],
    })
    base = {"date_col": "month", "count_col": "falls"}
    try:
        out = execute_template(db, None, project.id, upload.id, df, "u_c_chart", {**base, **params})
        return out
    finally:
        db.close()


def test_limitation_present_without_denominator_for_rate_outcome():
    assert _run({})["limitations"] == [NO_DENOMINATOR_LIMITATION]


def test_limitation_absent_with_denominator_or_count_outcome():
    assert "limitations" not in _run({"denominator_col": "patient_days"})
    assert "limitations" not in _run({}, kind="count")
