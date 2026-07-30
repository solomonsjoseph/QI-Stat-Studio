"""Focused report route tests for protected downloads and rendered report content."""
import io
import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from docx import Document
from fastapi.testclient import TestClient

from api.database import SessionLocal
from api.main import app
from api.models_db import AnalysisRun, AuditLog, EditHistory, IntakeAnswer, MentorComment, MentorShare, Project, Upload

PASSWORD = "password123"
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _register(test_client, email):
    response = test_client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _create_project_via_api(test_client, title="QI Report Project"):
    response = test_client.post("/projects", json={"title": title, "description": "Reduce variation"})
    assert response.status_code == 200, response.text
    return response.json()


def _docx_text(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    parts = [paragraph.text for paragraph in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def _pdf_text(content: bytes) -> str:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _seed_report_run(
    *,
    owner_user_id=None,
    use_run_upload=True,
    with_edits=False,
    with_audit_and_comments=False,
    dq_flags=None,
    acknowledged_flags=None,
    result=None,
):
    db = SessionLocal()
    now = datetime.utcnow()
    project = Project(
        owner_user_id=owner_user_id,
        title="Original Project Title",
        description="Improve timely follow-up",
        deadline="2030-01-31",
    )
    db.add(project)
    db.flush()

    legacy_upload = Upload(
        project_id=project.id,
        filename="legacy.csv",
        original_filename="legacy-source.csv",
        encrypted_path="/tmp/legacy.enc",
        quality_flags=json.dumps(dq_flags or []),
        acknowledged_flags=json.dumps(acknowledged_flags) if acknowledged_flags is not None else None,
    )
    db.add(legacy_upload)
    db.flush()

    analysis_upload = Upload(
        project_id=project.id,
        filename="analysis.csv",
        original_filename="analysis-source.csv",
        encrypted_path="/tmp/analysis.enc",
        quality_flags=json.dumps(dq_flags or []),
        acknowledged_flags=json.dumps(acknowledged_flags) if acknowledged_flags is not None else None,
    )
    db.add(analysis_upload)
    db.flush()

    run_result = result or {
        "methods": "A run chart was used to evaluate monthly performance.",
        "result_summary": "Median wait time improved from 10 to 7 days.",
        "interpretation": "AI-generated interpretation should be replaced.",
        "figure_base64": TINY_PNG_BASE64,
        "table": [{"period": "Baseline", "median": 10}, {"period": "Follow-up", "median": 7}],
    }
    run = AnalysisRun(
        project_id=project.id,
        upload_id=analysis_upload.id if use_run_upload else None,
        template="run_chart",
        parameters=json.dumps({"date_col": "month", "value_col": "wait_days"}),
        result_json=json.dumps(run_result),
        code_r="# reproducible R code",
        created_at=now,
    )
    db.add(run)
    db.flush()

    if with_edits:
        db.add_all(
            [
                EditHistory(
                    project_id=project.id,
                    field="title",
                    original_text="Original Project Title",
                    edited_text="Older title edit",
                    timestamp=now - timedelta(minutes=30),
                ),
                EditHistory(
                    project_id=project.id,
                    field="title",
                    original_text="Older title edit",
                    edited_text="Final resident report title",
                    timestamp=now - timedelta(minutes=3),
                ),
                EditHistory(
                    project_id=project.id,
                    field="caption",
                    original_text="",
                    edited_text="Resident-approved figure caption",
                    timestamp=now - timedelta(minutes=2),
                ),
                EditHistory(
                    project_id=project.id,
                    field="interpretation",
                    original_text="AI-generated interpretation should be replaced.",
                    edited_text="Resident interpretation with clinical context.",
                    timestamp=now - timedelta(minutes=1),
                ),
            ]
        )

    if with_audit_and_comments:
        db.add(
            AuditLog(
                project_id=project.id,
                action="analysis_completed",
                metadata_json=json.dumps({"template": "run_chart", "upload_id": analysis_upload.id}),
                timestamp=now,
            )
        )
        share = MentorShare(
            project_id=project.id,
            token="report-content-token",
            mentor_email="mentor@example.com",
            created_at=now,
            expires_at=now + timedelta(days=30),
        )
        db.add(share)
        db.flush()
        db.add_all(
            [
                MentorComment(
                    share_id=share.id,
                    project_id=project.id,
                    author_name="Dr Mentor",
                    author_email="mentor@example.com",
                    text="Visible mentor feedback for the report.",
                    created_at=now,
                ),
                MentorComment(
                    share_id=share.id,
                    project_id=project.id,
                    author_name="Dr Mentor",
                    author_email="mentor@example.com",
                    text="Deleted mentor feedback must not render.",
                    created_at=now,
                    deleted_at=now,
                ),
            ]
        )

    db.commit()
    ids = {"project_id": project.id, "run_id": run.id, "analysis_upload_id": analysis_upload.id}
    db.close()
    return ids


def test_report_docx_and_pdf_downloads_require_owner_or_admin_authentication():
    admin_client = TestClient(app)
    owner_client = TestClient(app)
    other_client = TestClient(app)
    anonymous_client = TestClient(app)
    try:
        _register(admin_client, "admin@example.com")
        owner = _register(owner_client, "owner@example.com")
        _register(other_client, "other@example.com")
        seeded = _seed_report_run(owner_user_id=owner["id"])

        assert anonymous_client.get(f"/report/{seeded['run_id']}/docx").status_code == 401
        assert anonymous_client.get(f"/report/{seeded['run_id']}/pdf").status_code == 401

        owner_docx = owner_client.get(f"/report/{seeded['run_id']}/docx")
        assert owner_docx.status_code == 200, owner_docx.text
        assert owner_docx.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        admin_pdf = admin_client.get(f"/report/{seeded['run_id']}/pdf")
        assert admin_pdf.status_code == 200, admin_pdf.text
        assert admin_pdf.headers["content-type"] == "application/pdf"
        assert admin_pdf.content[:4] == b"%PDF"

        with SessionLocal() as db:
            actions = [row.action for row in db.query(AuditLog).filter_by(project_id=seeded["project_id"]).all()]
            assert "report_downloaded" in actions

        assert other_client.get(f"/report/{seeded['run_id']}/docx").status_code == 403
        assert other_client.get(f"/report/{seeded['run_id']}/pdf").status_code == 403
    finally:
        admin_client.close()
        owner_client.close()
        other_client.close()
        anonymous_client.close()


def test_docx_report_renders_latest_edits_upload_lineage_audit_log_and_visible_mentor_comments(client):
    _register(client, "admin@example.com")
    seeded = _seed_report_run(with_edits=True, with_audit_and_comments=True)

    response = client.get(f"/report/{seeded['run_id']}/docx")
    assert response.status_code == 200, response.text
    text = _docx_text(response.content)

    assert "Final resident report title" in text
    assert "Older title edit" not in text.split("Methods", 1)[0]
    assert "Resident-approved figure caption" in text
    assert "Resident interpretation with clinical context." in text
    assert "AI-generated interpretation should be replaced." in text  # retained in Resident Edits audit table
    assert "analysis-source.csv" in text
    assert "legacy-source.csv" not in text
    assert "legacy upload lineage missing" not in text
    assert "Project Audit Log" in text
    assert "analysis_completed" in text
    assert f'"upload_id": {seeded["analysis_upload_id"]}' in text
    assert "Visible mentor feedback for the report." in text
    assert "Deleted mentor feedback must not render." not in text

def test_docx_report_appends_q7_intervention_to_figure_caption(client):
    _register(client, "admin@example.com")
    seeded = _seed_report_run()
    with SessionLocal() as db:
        db.add(
            IntakeAnswer(
                project_id=seeded["project_id"],
                question_key="q7",
                answer=json.dumps({"description": "Started standing orders", "date": "2025-01-01"}),
                is_unsure=False,
            )
        )
        db.commit()

    response = client.get(f"/report/{seeded['run_id']}/docx")
    assert response.status_code == 200, response.text
    text = _docx_text(response.content)

    assert "Intervention: Started standing orders (2025-01-01)" in text



def test_pdf_report_renders_latest_edits_upload_lineage_audit_log_and_visible_mentor_comments(client):
    _register(client, "admin@example.com")
    seeded = _seed_report_run(with_edits=True, with_audit_and_comments=True)

    response = client.get(f"/report/{seeded['run_id']}/pdf")
    assert response.status_code == 200, response.text
    text = _pdf_text(response.content)

    assert "Final resident report title" in text
    assert "Resident-approved figure caption" in text
    assert "Resident interpretation with clinical context." in text
    assert "analysis-source.csv" in text
    assert "legacy upload lineage missing" not in text
    assert "analysis_completed" in text
    assert "Visible mentor feedback for the report." in text
    assert "Deleted mentor feedback must not render." not in text



def test_pdf_report_escapes_tag_like_text_instead_of_crashing(client):
    """Resident-controlled text containing ReportLab markup characters (e.g. '<b>')
    must render as literal text, not be parsed as XML and crash PDF generation."""
    _register(client, "admin@example.com")
    seeded = _seed_report_run(result={
        "methods": "Compared groups where value <b>3</b> & threshold.",
        "result_summary": "Rate < 8% & trending down.",
        "interpretation": "A1c <target> improved & <b>stayed</b> stable.",
        "figure_base64": None,
        "table": [],
    })
    title_response = client.patch(
        f"/projects/{seeded['project_id']}",
        json={"title": "A1c <b>Goal</b> & Safety Project"},
    )
    assert title_response.status_code == 200, title_response.text

    response = client.get(f"/report/{seeded['run_id']}/pdf")
    assert response.status_code == 200, response.text
    text = _pdf_text(response.content)

    assert "A1c <b>Goal</b> & Safety Project" in text
    assert "value <b>3</b> & threshold" in text
    assert "A1c <target> improved & <b>stayed</b> stable." in text

def test_report_without_analysis_upload_id_uses_legacy_upload_and_marks_missing_lineage(client):
    _register(client, "admin@example.com")
    seeded = _seed_report_run(use_run_upload=False, result={
        "methods": "Legacy methods.",
        "result_summary": "Legacy summary.",
        "interpretation": "Legacy interpretation.",
        "figure_base64": None,
    })

    response = client.get(f"/report/{seeded['run_id']}/docx")
    assert response.status_code == 200, response.text
    text = _docx_text(response.content)

    assert "legacy-source.csv" in text
    assert "analysis-source.csv" not in text
    assert "legacy upload lineage missing" in text

def test_report_context_does_not_substitute_legacy_upload_when_run_upload_id_is_unresolved(client):
    _register(client, "admin@example.com")
    seeded = _seed_report_run(use_run_upload=False)

    with SessionLocal() as db:
        run = db.get(AnalysisRun, seeded["run_id"])
        run.upload_id = 987654321
        with db.no_autoflush:
            context = __import__("api.routers.report", fromlist=["_build_context"])._build_context(run, db)

    assert context["upload"] is None



def test_report_limitations_use_acknowledged_flags_instead_of_all_quality_flags(client):
    _register(client, "admin@example.com")
    all_flags = [
        {"col": "hba1c", "rule": "check_missing", "severity": "WARNING", "msg": "hba1c is 15% missing"},
        {"col": "egfr", "rule": "outlier_count", "severity": "WARNING", "msg": "egfr has outliers"},
    ]
    seeded = _seed_report_run(dq_flags=all_flags, acknowledged_flags=[all_flags[0]])

    response = client.get(f"/report/{seeded['run_id']}/docx")
    assert response.status_code == 200, response.text
    text = _docx_text(response.content)

    assert "hba1c is 15% missing" in text
    assert "egfr has outliers" not in text


def test_report_limitations_are_empty_when_acknowledged_flags_never_set(client):
    _register(client, "admin@example.com")
    all_flags = [
        {"col": "hba1c", "rule": "check_missing", "severity": "WARNING", "msg": "hba1c is 15% missing"},
        {"col": "egfr", "rule": "outlier_count", "severity": "WARNING", "msg": "egfr has outliers"},
    ]
    seeded = _seed_report_run(dq_flags=all_flags)

    with SessionLocal() as db:
        upload = db.get(Upload, seeded["analysis_upload_id"])
        assert upload.acknowledged_flags is None

    response = client.get(f"/report/{seeded['run_id']}/docx")
    assert response.status_code == 200, response.text
    text = _docx_text(response.content)

    assert "hba1c is 15% missing" not in text
    assert "egfr has outliers" not in text
    assert "No data quality issues were flagged for this dataset." in text


def test_project_edit_endpoint_persists_original_text_for_report_audit(client):
    _register(client, "admin@example.com")
    project = _create_project_via_api(client)

    response = client.post(
        f"/projects/{project['id']}/edits",
        json={
            "field": "interpretation",
            "original_text": "AI draft before resident edits",
            "edited_text": "Resident-approved interpretation",
        },
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        edit = db.query(EditHistory).filter_by(project_id=project["id"]).one()
        assert edit.field == "interpretation"
        assert edit.original_text == "AI draft before resident edits"
        assert edit.edited_text == "Resident-approved interpretation"


def test_project_title_edit_updates_project_metadata_with_edit_history(client):
    _register(client, "admin@example.com")
    project = _create_project_via_api(client, title="Original title")

    response = client.post(
        f"/projects/{project['id']}/edits",
        json={
            "field": "title",
            "original_text": "Original title",
            "edited_text": "Resident-approved title",
        },
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        saved = db.get(Project, project["id"])
        edit = db.query(EditHistory).filter_by(project_id=project["id"], field="title").one()
        assert saved.title == "Resident-approved title"
        assert edit.original_text == "Original title"
        assert edit.edited_text == "Resident-approved title"


def test_report_audit_trail_sanitizes_phi_like_project_update_metadata(client):
    _register(client, "admin@example.com")
    seeded = _seed_report_run(with_edits=True)
    sensitive_title = "Patient Jane Doe MRN 12345 readmission project"
    sensitive_description = "Follow-up for jane.doe@example.com with DOB 01/02/1970"
    sensitive_deadline = "2031-02-03"

    response = client.patch(
        f"/projects/{seeded['project_id']}",
        json={
            "title": sensitive_title,
            "description": sensitive_description,
            "deadline": sensitive_deadline,
        },
    )
    assert response.status_code == 200, response.text

    report = client.get(f"/report/{seeded['run_id']}/docx")
    assert report.status_code == 200, report.text
    text = _docx_text(report.content)

    assert "project_updated" in text
    assert '"fields": ["deadline", "description", "title"]' in text
    assert sensitive_title not in text
    assert sensitive_description not in text
    assert sensitive_deadline not in text
