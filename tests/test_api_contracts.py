from api.database import SessionLocal
from api.models_db import EditHistory


def _register(client, email="admin@example.com"):
    response = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()


def _project(client):
    response = client.post("/projects", json={"title": "QI", "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_analyze_run_rejects_legacy_params_field(client):
    _register(client)
    project_id = _project(client)

    response = client.post(
        "/analyze/run",
        json={"project_id": project_id, "upload_id": 1, "template": "run_chart", "params": {"value_col": "x"}},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "parameters" in body["error"]["field_errors"]
    assert "params" in body["error"]["field_errors"]
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


def test_analyze_run_accepts_parameters_contract_until_upload_lookup(client):
    _register(client)
    project_id = _project(client)

    response = client.post(
        "/analyze/run",
        json={"project_id": project_id, "upload_id": 999, "template": "run_chart", "parameters": {"value_col": "x"}},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Upload not found"


def test_edit_contract_persists_original_text(client):
    _register(client)
    project_id = _project(client)

    response = client.post(
        f"/projects/{project_id}/edits",
        json={"field": "interpretation", "original_text": "before", "edited_text": "after"},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        edit = db.query(EditHistory).filter_by(project_id=project_id).one()
        assert edit.field == "interpretation"
        assert edit.original_text == "before"
        assert edit.edited_text == "after"


def test_error_envelope_propagates_request_id(client):
    _register(client)

    response = client.get("/projects/999", headers={"X-Request-ID": "request-from-test"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "request-from-test"
    assert response.json() == {
        "error": {
            "code": "HTTP_404",
            "message": "Project not found",
            "field_errors": {},
            "request_id": "request-from-test",
        }
    }


def test_settings_registry_rejects_secret_keys_for_admin(client):
    _register(client)

    response = client.put("/settings", json={"key": "fernet_key", "value": "nope"})

    assert response.status_code == 400
    assert "cannot be changed at runtime" in response.json()["error"]["message"]
