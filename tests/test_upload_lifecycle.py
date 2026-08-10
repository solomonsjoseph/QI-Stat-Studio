import hashlib
import json
from pathlib import Path

from api.database import SessionLocal
from api.models_db import AuditLog, Upload
from api.routers import upload as upload_router


def _project(client):
    response = client.post("/projects", json={"title": "QI", "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _upload_csv(client, project_id, content, filename="data.csv"):
    return client.post(
        f"/upload/{project_id}",
        files={"file": (filename, content, "text/csv")},
    )


def test_upload_persists_safe_metadata_and_column_mapping(auth_client):
    project_id = _project(auth_client)
    raw = b"encounter_id,value\n1,10\n2,20\n"

    response = _upload_csv(auth_client, project_id, raw, filename="../../unsafe.csv")

    assert response.status_code == 200, response.text
    upload_id = response.json()["upload_id"]
    with SessionLocal() as db:
        upload = db.get(Upload, upload_id)
        assert upload.original_filename == "../../unsafe.csv"
        assert upload.filename == "../../unsafe.csv"
        assert upload.file_type == "csv"
        assert upload.size_bytes == len(raw)
        assert upload.checksum_sha256 == hashlib.sha256(raw).hexdigest()
        assert upload.status == "active"
        assert upload.storage_key.startswith(f"{project_id}_")
        assert upload.storage_key.endswith(".csv.enc")
        assert "unsafe" not in upload.storage_key
        assert Path(upload.encrypted_path).name == upload.storage_key
        assert Path(upload.encrypted_path).exists()
        assert db.query(AuditLog).filter_by(project_id=project_id, action="upload_created").count() == 1

    fetched = auth_client.get(f"/upload/{upload_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == upload_id
    assert fetched.json()["checksum_sha256"] == hashlib.sha256(raw).hexdigest()

    listed = auth_client.get(f"/upload/project/{project_id}")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [upload_id]

    update = auth_client.put(
        f"/upload/{upload_id}/column-types",
        json={"col_types": {"encounter_id": "ID", "value": "Number"}, "column_map": {"value_col": "value"}},
    )
    assert update.status_code == 200, update.text
    with SessionLocal() as db:
        upload = db.get(Upload, upload_id)
        assert json.loads(upload.col_types) == {"encounter_id": "ID", "value": "Number"}
        assert json.loads(upload.column_map) == {"value_col": "value"}



def test_upload_response_includes_first_five_preview_rows(auth_client):
    project_id = _project(auth_client)
    raw = Path("tests/fixtures/diabetes_care_qi_full.csv").read_bytes()

    response = _upload_csv(auth_client, project_id, raw, filename="diabetes.csv")

    assert response.status_code == 200, response.text
    preview_rows = response.json()["preview_rows"]
    assert len(preview_rows) == 5
    assert preview_rows[0]["encounter_date"].startswith("202")
    assert preview_rows[0]["encounter_id"]
    assert preview_rows[0]["fib4_score"] is None

def test_upload_rejects_bad_project_type_size_parser_and_shape(auth_client, monkeypatch):
    missing_project = _upload_csv(auth_client, 999999, b"a\n1\n")
    assert missing_project.status_code == 404
    assert missing_project.json()["error"]["message"] == "Project not found"

    project_id = _project(auth_client)

    unsupported = auth_client.post(
        f"/upload/{project_id}",
        files={"file": ("data.txt", b"a\n1\n", "text/plain")},
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"]["message"] == "Unsupported file type: .txt"

    original_max_bytes = upload_router.MAX_BYTES
    monkeypatch.setattr(upload_router, "MAX_BYTES", 5)
    too_large = _upload_csv(auth_client, project_id, b"a\n123456\n")
    assert too_large.status_code == 400
    assert too_large.json()["error"]["message"] == "File exceeds 50 MB limit"
    monkeypatch.setattr(upload_router, "MAX_BYTES", original_max_bytes)

    header_only = _upload_csv(auth_client, project_id, b"a,b\n")
    assert header_only.status_code == 400
    assert header_only.json()["error"]["message"] == "Uploaded dataset must contain at least one row"

    all_empty_column = _upload_csv(auth_client, project_id, b"empty,value\n,1\n,2\n")
    assert all_empty_column.status_code == 400
    assert all_empty_column.json()["error"]["message"] == "Columns with no values are not allowed: empty"

    bad_excel = auth_client.post(
        f"/upload/{project_id}",
        files={"file": ("bad.xlsx", b"not an xlsx workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert bad_excel.status_code == 400
    assert bad_excel.json()["error"]["message"].startswith("Could not parse uploaded xlsx file:")


def test_numeric_period_values_warn_without_crashing(auth_client):
    project_id = _project(auth_client)
    response = _upload_csv(auth_client, project_id, b"period,value\n1,10\n2,20\n")

    assert response.status_code == 200, response.text
    flags = response.json()["quality_flags"]
    assert any(flag["rule"] == "unexpected_period_values" for flag in flags)


def test_leading_zero_columns_are_not_coerced_to_numbers(auth_client):
    project_id = _project(auth_client)
    raw = b"encounter_id,zip\n1,02139\n2,10001\n3,00501\n"

    response = _upload_csv(auth_client, project_id, raw, filename="zips.csv")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["col_summary"]["zip"]["dtype"] == "object"
    assert [row["zip"] for row in body["preview_rows"]] == ["02139", "10001", "00501"]
    # A column intentionally preserved as text to keep its leading zero must
    # not also be flagged as though it were mistakenly stored as text.
    assert not any(f["col"] == "zip" and f["rule"] == "numeric_stored_as_text" for f in body["quality_flags"])


def test_restore_leading_zero_columns_only_rereads_int_inferred_columns():
    """The leading-zero fix must not force a second full-file text parse: it
    should only re-read (via usecols) the specific columns pandas already
    inferred as int64, and leave every other column's dtype/values alone."""
    from api import upload_utils

    raw = b"encounter_id,zip,note\n1,02139,fine\n2,10001,ok\n3,00501,good\n"
    df, restored = upload_utils._read_dataframe(raw, "csv")

    assert restored == {"zip"}
    assert list(df["zip"]) == ["02139", "10001", "00501"]
    assert df["note"].dtype == object
    assert list(df["note"]) == ["fine", "ok", "good"]


def test_restore_leading_zero_columns_leaves_ordinary_numeric_columns_untouched():
    """A column with no leading-zero-shaped values must stay a genuine
    numeric dtype, not be swept into string preservation."""
    import pandas as pd
    from api import upload_utils

    raw = b"encounter_id,age\n1,45\n2,50\n3,60\n"
    df, restored = upload_utils._read_dataframe(raw, "csv")

    assert restored == set()
    assert pd.api.types.is_integer_dtype(df["age"])


def test_replace_delete_and_analysis_require_active_uploads(auth_client):
    project_id = _project(auth_client)
    first = _upload_csv(auth_client, project_id, b"value\n1\n2\n3\n", filename="first.csv")
    assert first.status_code == 200, first.text
    old_id = first.json()["upload_id"]
    with SessionLocal() as db:
        old_path = Path(db.get(Upload, old_id).encrypted_path)

    replacement = auth_client.post(
        f"/upload/{project_id}/replace/{old_id}",
        files={"file": ("second.csv", b"value\n4\n5\n6\n", "text/csv")},
    )
    assert replacement.status_code == 200, replacement.text
    new_id = replacement.json()["id"]
    assert replacement.json()["status"] == "active"

    with SessionLocal() as db:
        old_upload = db.get(Upload, old_id)
        new_upload = db.get(Upload, new_id)
        assert old_upload.status == "replaced"
        assert new_upload.status == "active"
        actions = [row.action for row in db.query(AuditLog).filter_by(project_id=project_id).all()]
        assert "upload_created" in actions
        assert "upload_replaced" in actions
        assert old_path.exists()
        new_path = Path(new_upload.encrypted_path)
        assert new_path.exists()

    listed = auth_client.get(f"/upload/project/{project_id}")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [new_id]

    inactive_analysis = auth_client.post(
        "/analyze/run",
        json={"project_id": project_id, "upload_id": old_id, "template": "descriptive_summary", "parameters": {"value_cols": ["value"]}},
    )
    assert inactive_analysis.status_code == 400
    assert inactive_analysis.json()["error"]["message"] == "Upload is not active"

    deleted = auth_client.delete(f"/upload/{new_id}")
    assert deleted.status_code == 200, deleted.text
    with SessionLocal() as db:
        upload = db.get(Upload, new_id)
        assert upload.status == "deleted"
        assert not Path(upload.encrypted_path).exists()
        assert db.query(AuditLog).filter_by(project_id=project_id, action="upload_deleted").count() == 1

    deleted_analysis = auth_client.post(
        "/analyze/run",
        json={"project_id": project_id, "upload_id": new_id, "template": "descriptive_summary", "parameters": {"value_cols": ["value"]}},
    )
    assert deleted_analysis.status_code == 400
    assert deleted_analysis.json()["error"]["message"] == "Upload is not active"


def test_analysis_missingness_block_message_is_non_overrideable(auth_client):
    project_id = _project(auth_client)
    response = _upload_csv(auth_client, project_id, b"date,outcome\n2024-01-01,1\n2024-02-01,\n2024-03-01,\n2024-04-01,4\n", filename="missing.csv")
    assert response.status_code == 200, response.text
    upload_id = response.json()["upload_id"]
    ack = auth_client.patch(f"/upload/{upload_id}/acknowledged-flags", json={"flags": response.json()["quality_flags"]})
    assert ack.status_code == 200, ack.text

    analysis = auth_client.post(
        "/analyze/run",
        json={"project_id": project_id, "upload_id": upload_id, "template": "run_chart", "parameters": {"date_col": "date", "value_col": "outcome"}},
    )

    assert analysis.status_code == 400
    assert analysis.json()["error"]["message"] == (
        "Column 'outcome' is 50.0% missing. Analysis requires <=30% missing in the selected outcome column. "
        "Choose a different outcome column or upload corrected data; warning acknowledgement does not override this safety check."
    )
