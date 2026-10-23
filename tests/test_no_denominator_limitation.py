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


def test_reviewed_flag_changes_wording_only_with_the_flag():
    from api.routers.analyze import REVIEWED_NO_DENOMINATOR_LIMITATION, _missing_denominator
    db = SessionLocal()
    try:
        p = Project(title="p", description="d", deadline="2030-01-01",
                    ai_project_design=json.dumps({"primary_outcome": {"kind": "rate"}}))
        db.add(p)
        db.flush()
        assert _missing_denominator(db, p.id, "u_c_chart", {}) == NO_DENOMINATOR_LIMITATION
        got = _missing_denominator(db, p.id, "u_c_chart", {}, flag_reviewed=True)
        assert got == REVIEWED_NO_DENOMINATOR_LIMITATION
        assert got == ("No denominator was assigned. The resident reviewed this flag and chose to run a "
                       "counts-only chart, which assumes the same exposure every period.")
        assert _missing_denominator(db, p.id, "p_chart", {}, flag_reviewed=True) == (
            "No denominator was assigned. The resident reviewed this flag and chose to run it with each "
            "record counted as one case in its period.")
        assert _missing_denominator(db, p.id, "u_c_chart", {"denominator_col": "x"}, flag_reviewed=True) is None
    finally:
        db.rollback()
        db.close()


def test_execute_template_snapshots_reviewed_wording():
    db = SessionLocal()
    try:
        out = _run_reviewed()
    finally:
        db.close()
    assert out["limitations"][0].startswith("No denominator was assigned. The resident reviewed this flag")


def _run_reviewed():
    db = SessionLocal()
    project = Project(title="p", description="d", deadline="2030-01-01",
                      ai_project_design=json.dumps({"primary_outcome": {"column": "falls", "kind": "rate"}}))
    db.add(project)
    db.flush()
    upload = Upload(project_id=project.id, filename="a.csv", original_filename="a.csv", encrypted_path="/tmp/a.enc")
    db.add(upload)
    db.flush()
    df = pd.DataFrame({"month": pd.date_range("2023-01-01", periods=12, freq="MS"),
                       "falls": [2, 3, 4, 2, 3, 5, 2, 3, 4, 2, 3, 4]})
    try:
        return execute_template(db, None, project.id, upload.id, df, "u_c_chart",
                                {"date_col": "month", "count_col": "falls"}, flag_reviewed=True)
    finally:
        db.close()
