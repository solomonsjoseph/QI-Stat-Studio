import json

import pandas as pd
import pytest
from fastapi import HTTPException

from api.cleaning_runtime import (
    StepsApplyError,
    load_cleaned_dataframe,
    rebuild_profile,
    recheck_flags,
)
from api.config import settings
from api.database import SessionLocal
from api.models_db import Project, Upload
from api.staleness import compute_inputs_fingerprint
from api.upload_utils import load_raw_upload_dataframe, load_upload_dataframe

CSV = b"id,month,falls\n1,2024-01,5\n1,2024-01,5\n2,2024-02,7\n3,2024-03,9\n"


@pytest.fixture
def upload(tmp_path):
    path = tmp_path / "u.enc"
    path.write_bytes(settings.fernet.encrypt(CSV))
    return Upload(
        encrypted_path=str(path),
        file_type="csv",
        col_types=json.dumps({"id": "Identifier", "month": "Date", "falls": "Numeric"}),
        handoff_steps="[]",
        handoff_revision=0,
        checksum_sha256="abc",
    )


def _steps(upload, steps):
    upload.handoff_steps = json.dumps(steps)
    upload.handoff_revision = (upload.handoff_revision or 0) + 1


def test_no_steps_equals_raw(upload):
    pd.testing.assert_frame_equal(load_upload_dataframe(upload), load_raw_upload_dataframe(upload))
    pd.testing.assert_frame_equal(load_cleaned_dataframe(upload), load_raw_upload_dataframe(upload))


def test_drop_rows_applies_by_default_and_raw_is_untouched(upload):
    _steps(upload, [{"op": "drop_rows", "where": {"column": "falls", "op": "gt", "value": 8}}])
    assert len(load_upload_dataframe(upload)) == 3
    assert len(load_raw_upload_dataframe(upload)) == 4
    df, report = load_cleaned_dataframe(upload, with_report=True)
    assert len(df) == 3 and len(report) == 1


def test_bad_step_raises_409(upload):
    _steps(upload, [{"op": "drop_column", "column": "nope"}])
    with pytest.raises(StepsApplyError) as e:
        load_upload_dataframe(upload)
    assert isinstance(e.value, HTTPException) and e.value.status_code == 409
    assert "could not be applied" in e.value.detail["message"]


def test_validate_and_run_see_cleaned_rows(auth_client):
    r = auth_client.post(
        "/projects/intake",
        data={"title": "T", "description": "Reduce falls on unit 4 over six months"},
        files={"file": ("d.csv", CSV, "text/csv")},
    )
    assert r.status_code == 200, r.text
    uid = r.json()["upload"]["id"] if "upload" in r.json() else None
    with SessionLocal() as db:
        u = db.get(Upload, uid) if uid else db.query(Upload).order_by(Upload.id.desc()).first()
        _steps(u, [{"op": "drop_rows", "where": {"column": "falls", "op": "gt", "value": 8}}])
        db.commit()
        assert len(load_upload_dataframe(u)) == 3
        u.handoff_steps = json.dumps([{"op": "drop_column", "column": "nope"}])
        db.commit()
        from api.routers import analyze

        with pytest.raises(StepsApplyError):
            analyze.load_upload_dataframe(u)


def test_fingerprint_stable_without_steps_and_changes_with_steps(upload):
    p = Project(description="d", ai_project_design="{}")
    legacy = compute_inputs_fingerprint(p, upload)
    upload.handoff_steps = "[]"
    upload.handoff_revision = 3  # revision alone must not move an empty-steps fingerprint
    assert compute_inputs_fingerprint(p, upload) == legacy
    _steps(upload, [{"op": "drop_duplicates"}])
    with_steps = compute_inputs_fingerprint(p, upload)
    assert with_steps != legacy
    upload.handoff_revision += 1
    assert compute_inputs_fingerprint(p, upload) != with_steps


def test_recheck_clears_duplicate_id_error(upload):
    ids = lambda: {f["id"]: f for f in recheck_flags(upload)}
    before = ids()
    dup = [f for f in before.values() if f["rule"] == "duplicate_id" or "duplicate" in f["rule"]]
    assert dup, before.keys()
    _steps(upload, [{"op": "drop_duplicates"}])
    after = ids()
    assert not [f for f in after.values() if "duplicate" in f["rule"] and f["severity"] == "ERROR"]
    assert all("id" in f for f in after.values())


def test_rebuild_profile(upload):
    class _Db:
        def add(self, _):
            pass

    _steps(upload, [{"op": "drop_duplicates"}])
    prof = rebuild_profile(upload, _Db())
    assert prof["row_count"] == 3
    assert json.loads(upload.dataset_profile)["row_count"] == 3


def test_build_data_changes_counts_resolves_warnings_and_lists_note_only_decisions(upload):
    from api.data_changes import build_data_changes

    assert build_data_changes(upload) is None
    upload.quality_flags = json.dumps([{"id": "w1", "msg": "falls has outliers"}])
    _steps(upload, [{"op": "drop_rows", "where": {"column": "falls", "op": "gt", "value": 8},
                     "warning_ids": ["w1"], "note": "mentor agreed"}])
    upload.handoff_revisions = json.dumps([
        {"kind": "created", "summary": "Handoff created from upload.", "steps_before_count": 0, "steps_after_count": 0},
        {"kind": "apply", "summary": "Kept id duplicates", "steps_before_count": 1, "steps_after_count": 1},
        {"kind": "revise", "summary": "Swapped one step for another", "steps_before_count": 1, "steps_after_count": 1},
    ])
    dc = build_data_changes(upload)
    s = dc["steps"][0]
    assert (s["rows_before"], s["rows_after"], s["rows_removed"]) == (4, 3, 1)
    assert s["warnings"] == ["falls has outliers"] and s["note"] == "mentor agreed"
    assert dc["decisions"] == ["Kept id duplicates"]
