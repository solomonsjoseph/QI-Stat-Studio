import json

from fastapi.testclient import TestClient

from api.database import SessionLocal
from api.main import app
from api.models_db import AnalysisRun, EditHistory, Project, Upload


def _register(client, email):
    response = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()


def _create_project(client, title="Owner project", description="Owned"):
    response = client.post("/projects", json={"title": title, "description": description})
    assert response.status_code == 200, response.text
    return response.json()


def test_projects_require_authentication(client):
    response = client.post("/projects", json={"title": "Aim", "description": "Improve care"})

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Authentication required"


def test_project_lifecycle_is_owner_scoped_paginated_and_ordered(client):
    admin_client = TestClient(app)
    owner_client = TestClient(app)
    other_client = TestClient(app)
    try:
        _register(admin_client, "admin@example.com")
        owner = _register(owner_client, "owner@example.com")
        _register(other_client, "other@example.com")

        first = _create_project(owner_client, "Beta", "Owned")
        second = _create_project(owner_client, "Alpha", "Owned")
        assert first["owner_user_id"] == owner["id"]

        owner_list = owner_client.get("/projects", params={"limit": 1, "offset": 0, "order": "title_asc"})
        assert owner_list.status_code == 200, owner_list.text
        body = owner_list.json()
        assert body["total"] == 2
        assert body["limit"] == 1
        assert [p["title"] for p in body["items"]] == ["Alpha"]

        denied = other_client.get(f"/projects/{first['id']}")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "HTTP_403"

        allowed = admin_client.get(f"/projects/{first['id']}")
        assert allowed.status_code == 200
        assert allowed.json()["id"] == first["id"]

        patched = owner_client.patch(f"/projects/{first['id']}", json={"title": "Updated", "status": "active"})
        assert patched.status_code == 200, patched.text
        assert patched.json()["title"] == "Updated"
        assert patched.json()["status"] == "active"

        archived = owner_client.delete(f"/projects/{first['id']}")
        assert archived.status_code == 200, archived.text
        assert archived.json() == {"ok": True, "purged": False}

        default_list = owner_client.get("/projects")
        assert [p["id"] for p in default_list.json()["items"]] == [second["id"]]

        archived_list = owner_client.get("/projects", params={"status": "archived"})
        assert [p["id"] for p in archived_list.json()["items"]] == [first["id"]]
        assert archived_list.json()["items"][0]["archived_at"] is not None
    finally:
        admin_client.close()
        owner_client.close()
        other_client.close()


def test_ownerless_legacy_project_is_admin_only_and_claimable(client):
    admin_client = TestClient(app)
    resident_client = TestClient(app)
    try:
        _register(admin_client, "admin@example.com")
        resident = _register(resident_client, "resident@example.com")
        with SessionLocal() as db:
            project = Project(title="Legacy", description="No owner", status="draft")
            db.add(project)
            db.commit()
            db.refresh(project)
            project_id = project.id

        assert resident_client.get(f"/projects/{project_id}").status_code == 403
        assert admin_client.get(f"/projects/{project_id}").status_code == 200

        denied_claim = resident_client.post(f"/projects/{project_id}/claim", json={"owner_user_id": resident["id"]})
        assert denied_claim.status_code == 403

        claimed = admin_client.post(f"/projects/{project_id}/claim", json={"owner_user_id": resident["id"]})
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["owner_user_id"] == resident["id"]
        assert resident_client.get(f"/projects/{project_id}").status_code == 200
    finally:
        admin_client.close()
        resident_client.close()


def test_project_resume_derives_wizard_state_and_hydrates_latest_records(client):
    _register(client, "owner@example.com")
    project = _create_project(client, "Resume", "")
    project_id = project["id"]

    response = client.get(f"/projects/{project_id}/resume")
    assert response.status_code == 200, response.text
    assert response.json()["current_screen"] == "description"

    client.post(f"/intake/{project_id}", json={"answers": {"q1": "Improve follow-up"}})
    assert client.get(f"/projects/{project_id}/resume").json()["current_screen"] == "intake"

    answers = {
        "q2": "percentage",
        "q3": "No — I'm just describing one time period",
        "q4": "Tracking over time (months, weeks, days)",
        "q5": "Monthly",
        "q6": "12",
        "q7": {"description": "Should be removed", "date": "2026-01-01"},
        "q8": "Same unit pre vs. post",
        "q9": "R",
        "q10": {},
    }
    saved = client.post(f"/intake/{project_id}", json={"answers": answers})
    assert saved.status_code == 200, saved.text
    resumed = client.get(f"/projects/{project_id}/resume").json()
    assert resumed["current_screen"] == "upload"
    assert "q7" not in resumed["answers"]
    assert "q8" not in resumed["answers"]

    comparison_project = _create_project(client, "Comparison Resume", "")
    comparison_id = comparison_project["id"]
    comparison_answers = {
        "q1": "Compare pre/post process",
        "q2": "average",
        "q3": "Yes — before and after an intervention",
        "q4": "Tracking over time (months, weeks, days)",
        "q5": "Monthly",
        "q6": "12",
        "q7": {},
        "q8": "Same unit pre vs. post",
        "q9": "R",
        "q10": {},
    }
    comparison_saved = client.post(f"/intake/{comparison_id}", json={"answers": comparison_answers})
    assert comparison_saved.status_code == 200, comparison_saved.text
    assert client.get(f"/projects/{comparison_id}/resume").json()["current_screen"] == "upload"

    with SessionLocal() as db:
        upload = Upload(
            project_id=project_id,
            filename="data.csv",
            original_filename="data.csv",
            file_type="csv",
            size_bytes=10,
            checksum_sha256="abc",
            storage_key="safe.enc",
            encrypted_path="uploads_enc/safe.enc",
            status="active",
            col_types=json.dumps({"month": "Date"}),
            column_map=json.dumps({"date_col": "month"}),
            quality_flags=json.dumps([{"level": "warning", "message": "Missing values"}]),
        )
        db.add(upload)
        db.commit()
        db.refresh(upload)
        upload_id = upload.id

    resumed = client.get(f"/projects/{project_id}/resume").json()
    assert resumed["current_screen"] == "review"
    assert resumed["latest_upload"]["id"] == upload_id
    assert resumed["latest_upload"]["column_map"] == {"date_col": "month"}

    with SessionLocal() as db:
        upload = db.get(Upload, upload_id)
        upload.acknowledged_flags = upload.quality_flags
        db.add(AnalysisRun(project_id=project_id, upload_id=upload_id, template="run_chart", parameters="{}", result_json="{\"interpretation\":\"ok\"}"))
        db.commit()

    resumed = client.get(f"/projects/{project_id}/resume").json()
    assert resumed["current_screen"] == "edit"
    assert resumed["latest_run"]["template"] == "run_chart"

    with SessionLocal() as db:
        db.add(EditHistory(project_id=project_id, field="interpretation", original_text="", edited_text="done"))
        db.commit()

    assert client.get(f"/projects/{project_id}/resume").json()["current_screen"] == "download"


def test_project_purge_removes_project_and_encrypted_upload_file(client, tmp_path):
    _register(client, "owner@example.com")
    project = _create_project(client, "Purge", "Remove")
    upload_path = tmp_path / "upload.enc"
    upload_path.write_text("encrypted")

    with SessionLocal() as db:
        db.add(
            Upload(
                project_id=project["id"],
                filename="data.csv",
                original_filename="data.csv",
                encrypted_path=str(upload_path),
            )
        )
        db.commit()

    response = client.delete(f"/projects/{project['id']}", params={"purge": True})
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "purged": True}
    assert not upload_path.exists()

    with SessionLocal() as db:
        assert db.get(Project, project["id"]) is None
