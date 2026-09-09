import io
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.database import SessionLocal
from api.models_db import AuditLog, Project, Upload
from api.phi_gate import PhiGateResult, scan_document_text, scan_upload


def _register(client, email="phigate@example.com"):
    client.post("/auth/register", json={"email": email, "password": "password123"})


def test_patient_name_column_blocked():
    df = pd.DataFrame({"patient_name": ["Alice", "Bob"], "val": [1, 2]})
    res = scan_upload(df, None)
    assert res.status == "blocked"
    assert any(f.column == "patient_name" and f.category == "Patient Name" for f in res.findings)


def test_mrn_column_blocked():
    df = pd.DataFrame({"mrn": ["100234", "100567"], "val": [1, 2]})
    res = scan_upload(df, None)
    assert res.status == "blocked"
    assert any(f.column == "mrn" and f.category == "Medical Record Number" for f in res.findings)


def test_contact_info_blocked():
    df = pd.DataFrame({"phone_num": ["555-123-4567", "555-987-6543"], "val": [1, 2]})
    res = scan_upload(df, None)
    assert res.status == "blocked"
    assert any(f.column == "phone_num" and f.category == "Phone Number" for f in res.findings)


def test_sequential_internal_ids_accepted():
    df = pd.DataFrame({"study_id": list(range(1, 41)), "score": [10] * 40})
    res = scan_upload(df, None)
    assert res.status == "passed"
    assert len(res.findings) == 0


def test_dictionary_containing_patient_name_blocked():
    df = pd.DataFrame({"study_id": [1, 2], "score": [10, 20]})
    dict_text = "Patient: Jane Doe, MRN 100234"
    res = scan_upload(df, dict_text)
    assert res.status == "blocked"
    assert any(f.source == "dictionary" and f.category == "Patient Name" for f in res.findings)


def test_scanner_exception_yields_status_error_and_fails_closed(monkeypatch):
    import api.phi_gate

    def mock_fail(*args, **kwargs):
        raise RuntimeError("simulated scanner explosion")

    monkeypatch.setattr(api.phi_gate, "scan_dataframe_for_phi", mock_fail)
    df = pd.DataFrame({"study_id": [1, 2], "score": [10, 20]})
    res = scan_upload(df, None)
    assert res.status == "error"
    assert res.findings == []


def test_blocked_upload_creates_zero_rows_and_no_file(auth_client, tmp_path):
    _register(auth_client, "gate_test@example.com")
    resp = auth_client.post(
        "/projects/intake",
        data={"title": "PHI Test", "description": "desc"},
        files={
            "file": ("data.csv", b"patient_name,mrn,val\nJane Doe,100234,10\n", "text/csv"),
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert (
        data["error"]["message"]
        == "We can't process this file because it may contain patient-identifying information. Remove all names, MRNs, and other PHI, then upload it again."
    )
    assert "patient_name" in data["error"]["field_errors"]
    assert "mrn" in data["error"]["field_errors"]

    with SessionLocal() as db:
        assert db.query(Project).filter_by(title="PHI Test").count() == 0
        assert db.query(Upload).count() == 0


def test_blocked_upload_audit_contains_no_cell_values(auth_client):
    _register(auth_client, "audit_test@example.com")
    # First create a clean project
    clean_resp = auth_client.post(
        "/projects/intake",
        data={"title": "Audit Test", "description": "desc"},
        files={"file": ("clean.csv", b"study_id,val\n1,10\n", "text/csv")},
    )
    assert clean_resp.status_code == 200, clean_resp.text
    pid = clean_resp.json()["project"]["id"]

    # Now upload a PHI-blocked file to this project
    resp = auth_client.post(
        f"/upload/{pid}",
        files={"file": ("phi.csv", b"mrn,secret_name\n999999,SuperSecretPerson\n", "text/csv")},
    )
    assert resp.status_code == 422

    with SessionLocal() as db:
        logs = db.query(AuditLog).filter_by(project_id=pid, action="upload_blocked_phi").all()
        assert len(logs) == 1
        meta = logs[0].metadata_json
        assert "999999" not in meta
        assert "SuperSecretPerson" not in meta
        assert "categories" in meta
        assert "sources" in meta
