import json

from fastapi.testclient import TestClient

from api.database import SessionLocal
from api.main import app
from api.models_db import AnalysisRun, FailureLog, Upload
from api.config import settings


def _test_failure(project_id: int):
    raise RuntimeError(f"synthetic failure for project {project_id}")


def _test_failure_body(payload: dict):
    raise RuntimeError(f"raw failure body must not persist {payload}")


def _test_token_failure(token: str):
    raise RuntimeError(f"raw token must not persist {token}")


if not any(getattr(route, "path", None) == "/__test/failure/{project_id}" for route in app.routes):
    app.add_api_route("/__test/failure/{project_id}", _test_failure, methods=["GET"])
if not any(getattr(route, "path", None) == "/__test/failure-body" for route in app.routes):
    app.add_api_route("/__test/failure-body", _test_failure_body, methods=["POST"])
if not any(getattr(route, "path", None) == "/__test/share/{token}/failure" for route in app.routes):
    app.add_api_route("/__test/share/{token}/failure", _test_token_failure, methods=["GET"])

for _path in ("/__test/failure-body", "/__test/share/{token}/failure"):
    _idx = next(idx for idx, route in enumerate(app.router.routes) if getattr(route, "path", None) == _path)
    _route_obj = app.router.routes.pop(_idx)
    _mount_idx = next((idx for idx, route in enumerate(app.router.routes) if getattr(route, "path", None) in {"", "/"}), len(app.router.routes))
    app.router.routes.insert(_mount_idx, _route_obj)

test_index = next(idx for idx, route in enumerate(app.router.routes) if getattr(route, "path", None) == "/__test/failure/{project_id}")
_test_route_obj = app.router.routes.pop(test_index)
mount_index = next((idx for idx, route in enumerate(app.router.routes) if getattr(route, "path", None) in {"", "/"}), len(app.router.routes))
app.router.routes.insert(mount_index, _test_route_obj)
app.middleware_stack = None


def _register_admin(client):
    response = client.post("/auth/register", json={"email": "admin@example.com", "password": "password123"})
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"


def _project_id(client):
    _register_admin(client)
    response = client.post("/projects", json={"title": "Ops project", "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_health_is_public_and_sets_request_id(client):
    response = client.get("/health", headers={"X-Request-ID": "req-health"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "req-health"


def test_readyz_checks_database_and_fernet(client):
    response = client.get("/readyz")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready"}


def test_readyz_reports_fernet_misconfiguration_without_startup_abort(client, monkeypatch):
    monkeypatch.setattr(settings, "fernet_key", "")

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": True, "fernet": False}}


def test_error_envelope_contains_request_id(client):
    response = client.get("/projects", headers={"X-Request-ID": "req-envelope"})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "req-envelope"
    assert response.json() == {
        "error": {
            "code": "HTTP_401",
            "message": "Authentication required",
            "field_errors": {},
            "request_id": "req-envelope",
        }
    }


def test_unhandled_exception_records_failure_and_admin_can_filter_by_request_id(client):
    project_id = _project_id(client)

    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        # Reuse the authenticated admin cookie from the fixture client.
        no_raise_client.cookies.update(client.cookies)
        response = no_raise_client.get(f"/__test/failure/{project_id}", headers={"X-Request-ID": "req-failure"})
        assert response.status_code == 500
        assert response.json()["error"]["request_id"] == "req-failure"

        failures = no_raise_client.get("/admin/failures", params={"request_id": "req-failure"})

    assert failures.status_code == 200, failures.text
    data = failures.json()
    assert data["total"] == 1
    row = data["items"][0]
    assert row["request_id"] == "req-failure"
    assert row["project_id"] == project_id
    assert row["route"] == "/__test/failure/{project_id}"
    assert row["message"] == "Unexpected server error"



def test_failure_log_uses_safe_message_route_template_and_sanitized_body_ids(client):
    project_id = _project_id(client)
    with SessionLocal() as db:
        upload = Upload(project_id=project_id, filename="safe.csv", original_filename="safe.csv", encrypted_path="/tmp/safe.enc")
        db.add(upload)
        db.flush()
        run = AnalysisRun(project_id=project_id, upload_id=upload.id, template="run_chart")
        db.add(run)
        db.commit()
        upload_id = upload.id
        run_id = run.id

    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        no_raise_client.cookies.update(client.cookies)
        response = no_raise_client.post(
            "/__test/failure-body",
            headers={"X-Request-ID": "req-body-failure"},
            json={
                "project_id": project_id,
                "upload_id": upload_id,
                "run_id": run_id,
                "prompt": "MRN 123456 and secret@example.com",
            },
        )
        assert response.status_code == 500
        failures = no_raise_client.get("/admin/failures", params={"request_id": "req-body-failure"})

    assert failures.status_code == 200, failures.text
    row = failures.json()["items"][0]
    assert row["message"] == "Unexpected server error"
    assert row["route"] == "/__test/failure-body"
    assert row["project_id"] == project_id
    assert row["upload_id"] == upload_id
    assert row["run_id"] == run_id
    serialized = json.dumps(row)
    assert "MRN 123456" not in serialized
    assert "secret@example.com" not in serialized
    assert "prompt" not in serialized


def test_failure_log_never_persists_share_tokens(client):
    _register_admin(client)
    sensitive_token = "token-secret@example.com-MRN-123456"

    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        no_raise_client.cookies.update(client.cookies)
        response = no_raise_client.get(
            f"/__test/share/{sensitive_token}/failure",
            headers={"X-Request-ID": "req-token-failure"},
        )
        assert response.status_code == 500
        failures = no_raise_client.get("/admin/failures", params={"request_id": "req-token-failure"})

    assert failures.status_code == 200, failures.text
    row = failures.json()["items"][0]
    assert row["route"] == "/__test/share/{token}/failure"
    assert row["message"] == "Unexpected server error"
    assert sensitive_token not in json.dumps(row)

def test_admin_failures_requires_admin(client):
    response = client.get("/admin/failures")

    assert response.status_code == 401
