from api.database import SessionLocal
from api.models_db import Project, Upload


def _dictionary(text=b"encounter_id: sequential study id, non-identifying."):
    return ("dictionary.txt", text, "text/plain")


def _intake(client, *, title="Falls QI", description="Reduce falls on 3W", dataset=b"encounter_id,value\n1,10\n2,20\n", dictionary=None):
    return client.post(
        "/projects/intake",
        data={"title": title, "description": description},
        files={
            "file": ("data.csv", dataset, "text/csv"),
            "dictionary": dictionary or _dictionary(),
        },
    )


def test_intake_creates_project_and_upload_together_in_one_request(auth_client):
    response = _intake(auth_client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project"]["title"] == "Falls QI"
    assert body["upload"]["col_types"] == {"encounter_id": "ID", "value": "Number"}

    with SessionLocal() as db:
        project = db.get(Project, body["project"]["id"])
        upload = db.get(Upload, body["upload"]["id"])
        assert project is not None
        assert upload is not None
        assert upload.project_id == project.id
        assert upload.dictionary_filename == "dictionary.txt"
        assert upload.phi_scan_status == "clean"


def test_intake_requires_a_dictionary_file(auth_client):
    response = auth_client.post(
        "/projects/intake",
        data={"title": "No dictionary", "description": "desc"},
        files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
    )

    assert response.status_code == 422

    with SessionLocal() as db:
        assert db.query(Project).count() == 0


def test_intake_rejects_phi_and_creates_no_project_or_upload(auth_client):
    response = _intake(auth_client, dataset=b"patient_name,mrn,age\nJane Doe,100234,72\nJohn Smith,100567,65\n")

    assert response.status_code == 422
    field_errors = response.json()["error"]["field_errors"]
    assert set(field_errors.keys()) == {"patient_name", "mrn"}

    with SessionLocal() as db:
        assert db.query(Project).count() == 0
        assert db.query(Upload).count() == 0


def test_intake_dictionary_clears_an_ambiguous_column_but_not_a_real_identifier(auth_client):
    dictionary = _dictionary(
        b"batch_ref: an internal batch code formatted like a phone number, non-identifying, not phi. "
        b"mrn: this is the patient's real medical record number."
    )
    response = _intake(
        auth_client,
        dataset=b"batch_ref,mrn,value\n555-123-4567,100234,10\n555-987-6543,100567,20\n",
        dictionary=dictionary,
    )

    assert response.status_code == 422
    field_errors = response.json()["error"]["field_errors"]
    assert set(field_errors.keys()) == {"mrn"}
