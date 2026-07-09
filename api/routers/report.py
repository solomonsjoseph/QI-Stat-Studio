from __future__ import annotations

import base64
import io
import json
from datetime import datetime
from typing import Any

from docx import Document
from docx.shared import Inches
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from api.audit import log_action, sanitize_audit_metadata
from api.auth import get_current_user
from api.database import get_db
from api.models_db import AnalysisRun, AuditLog, EditHistory, MentorComment, Project, Upload, User
from api.routers.intake import _load_answers

router = APIRouter(prefix="/report", tags=["report"])
_REPORT_EDIT_FIELDS = {"title", "caption", "interpretation"}


def _safe_json(raw: str | None, fallback: Any):
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _get_run_or_404(run_id: int, db: Session):
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run


def _require_run_access(run: AnalysisRun, db: Session, user: User):
    project = db.get(Project, run.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if user.role != "admin" and project.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Project access denied")


def _latest_edits(project_id: int, db: Session) -> dict[str, EditHistory]:
    rows = (
        db.query(EditHistory)
        .filter(EditHistory.project_id == project_id, EditHistory.field.in_(_REPORT_EDIT_FIELDS))
        .order_by(EditHistory.timestamp.desc(), EditHistory.id.desc())
        .all()
    )
    latest: dict[str, EditHistory] = {}
    for row in rows:
        if row.field not in latest:
            latest[row.field] = row
    return latest


def _run_upload(run: AnalysisRun, db: Session) -> Upload | None:
    if run.upload_id is not None:
        return db.get(Upload, run.upload_id)
    return db.query(Upload).filter(Upload.project_id == run.project_id).order_by(Upload.id.asc()).first()


def _build_context(run: AnalysisRun, db: Session) -> dict[str, Any]:
    project = db.query(Project).filter(Project.id == run.project_id).first()
    upload = _run_upload(run, db)
    result = _safe_json(run.result_json, {})
    params = _safe_json(run.parameters, {})
    if upload is not None:
        flags = _safe_json(upload.acknowledged_flags, [])
    else:
        flags = []

    edits = _latest_edits(run.project_id, db)
    title_edit = edits.get("title")
    caption_edit = edits.get("caption")
    interpretation_edit = edits.get("interpretation")

    report_title = (
        title_edit.edited_text
        if title_edit and title_edit.edited_text
        else (project.title if project and project.title else f"Project {run.project_id}")
    )
    caption = caption_edit.edited_text if caption_edit and caption_edit.edited_text else ""
    answers = _load_answers(db, run.project_id)
    q7 = answers.get("q7")
    if isinstance(q7, dict) and q7.get("date"):
        intervention_note = f"Intervention: {q7.get('description', 'Intervention')} ({q7['date']})"
        caption = f"{caption} {intervention_note}".strip()
    interpretation = (
        interpretation_edit.edited_text
        if interpretation_edit and interpretation_edit.edited_text
        else result.get("interpretation", "")
    )
    result = dict(result)
    if interpretation:
        result["interpretation"] = interpretation

    return {
        "report_title": report_title,
        "caption": caption,
        "interpretation": interpretation,
        "project": project,
        "upload": upload,
        "result": result,
        "params": params,
        "flags": flags,
        "edits": edits,
    }


def _source_filename(upload: Upload | None) -> str:
    if not upload:
        return "N/A"
    return upload.original_filename or upload.filename or "N/A"


def _run_datetime(run: AnalysisRun) -> datetime:
    return run.created_at or datetime.utcnow()


def _audit_metadata_summary(raw: str | None) -> str:
    value = _safe_json(raw, {})
    safe_value = sanitize_audit_metadata(value)
    if safe_value in ({}, [], None, ""):
        return ""
    if isinstance(safe_value, (dict, list)):
        return json.dumps(safe_value, sort_keys=True)
    return str(safe_value)


def _audit_entries(project_id: int, db: Session) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(AuditLog.project_id == project_id)
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )


def _mentor_comments(project_id: int, db: Session, share_id: int | None = None) -> list[MentorComment]:
    query = db.query(MentorComment).filter(
        MentorComment.project_id == project_id,
        MentorComment.deleted_at.is_(None),
    )
    if share_id is not None:
        query = query.filter(MentorComment.share_id == share_id)
    return query.order_by(MentorComment.created_at.asc(), MentorComment.id.asc()).all()


def _base_audit_rows(run: AnalysisRun, context: dict[str, Any]) -> list[list[str]]:
    upload = context["upload"]
    rows = [
        ["Template", run.template or ""],
        ["Parameters", json.dumps(context["params"], indent=2, sort_keys=True)],
        ["Source file", _source_filename(upload)],
        ["Run date", _run_datetime(run).strftime("%Y-%m-%d %H:%M UTC")],
    ]
    if run.upload_id is None:
        rows.append(["Lineage note", "legacy upload lineage missing"])
    return rows


def _build_docx(run: AnalysisRun, db: Session, share_id: int | None = None) -> bytes:
    context = _build_context(run, db)
    result = context["result"]
    flags = context["flags"]

    doc = Document()
    doc.add_heading("QI Stat Studio Report", 0)
    doc.add_heading(context["report_title"], 1)

    doc.add_heading("Methods", 1)
    doc.add_paragraph(result.get("methods", "No methods description available."))

    doc.add_heading("Results", 1)
    doc.add_paragraph(result.get("result_summary", ""))

    tbl_data = result.get("table", [])
    if tbl_data:
        headers = list(tbl_data[0].keys())
        rt = doc.add_table(rows=1 + len(tbl_data), cols=len(headers))
        rt.style = "Table Grid"
        for j, h in enumerate(headers):
            rt.rows[0].cells[j].text = h.capitalize()
        for i, row in enumerate(tbl_data, 1):
            for j, h in enumerate(headers):
                rt.rows[i].cells[j].text = str(row.get(h, ""))

    fig_b64 = result.get("figure_base64")
    if fig_b64:
        img_data = base64.b64decode(fig_b64)
        doc.add_picture(io.BytesIO(img_data), width=Inches(5.5))
        if context["caption"]:
            doc.add_paragraph(context["caption"])

    doc.add_heading("Interpretation", 1)
    doc.add_paragraph(context["interpretation"] or "[Resident interpretation will appear here after editing]")

    doc.add_heading("Limitations", 1)
    if flags:
        for f in flags:
            doc.add_paragraph(f"• {f.get('msg') or f.get('message') or str(f)}", style="List Bullet")
    else:
        doc.add_paragraph("No data quality issues were flagged for this dataset.")

    if run.code_r:
        doc.add_heading("Statistical Code Supplement (R)", 1)
        doc.add_paragraph(run.code_r, style="No Spacing")
    if run.code_spss:
        doc.add_heading("Statistical Code Supplement (SPSS)", 1)
        doc.add_paragraph(run.code_spss, style="No Spacing")
    if run.code_sas:
        doc.add_heading("Statistical Code Supplement (SAS)", 1)
        doc.add_paragraph(run.code_sas, style="No Spacing")

    comments = _mentor_comments(run.project_id, db, share_id=share_id)
    if comments:
        doc.add_heading("Mentor Feedback", 1)
        for comment in comments:
            when = comment.created_at.strftime("%Y-%m-%d %H:%M UTC") if comment.created_at else ""
            author = comment.author_name or "Mentor"
            email = f" <{comment.author_email}>" if comment.author_email else ""
            doc.add_paragraph(f"{when} — {author}{email}: {comment.text}")

    doc.add_heading("Audit Trail", 1)
    audit_rows = _base_audit_rows(run, context)
    tbl = doc.add_table(rows=len(audit_rows), cols=2)
    tbl.style = "Table Grid"
    for i, (key, value) in enumerate(audit_rows):
        tbl.rows[i].cells[0].text = key
        tbl.rows[i].cells[1].text = str(value)

    audit_entries = _audit_entries(run.project_id, db)
    if audit_entries:
        doc.add_heading("Project Audit Log", 2)
        audit_tbl = doc.add_table(rows=1 + len(audit_entries), cols=3)
        audit_tbl.style = "Table Grid"
        for j, header in enumerate(["Timestamp", "Action", "Metadata"]):
            audit_tbl.rows[0].cells[j].text = header
        for i, entry in enumerate(audit_entries, 1):
            audit_tbl.rows[i].cells[0].text = entry.timestamp.strftime("%Y-%m-%d %H:%M UTC") if entry.timestamp else ""
            audit_tbl.rows[i].cells[1].text = entry.action or ""
            audit_tbl.rows[i].cells[2].text = _audit_metadata_summary(entry.metadata_json)

    edits = list(context["edits"].values())
    if edits:
        doc.add_heading("Resident Edits", 2)
        edit_tbl = doc.add_table(rows=1 + len(edits), cols=3)
        edit_tbl.style = "Table Grid"
        for j, header in enumerate(["Field", "Original Text", "Edited Text"]):
            edit_tbl.rows[0].cells[j].text = header
        for i, edit in enumerate(edits, 1):
            edit_tbl.rows[i].cells[0].text = edit.field or ""
            edit_tbl.rows[i].cells[1].text = edit.original_text or ""
            edit_tbl.rows[i].cells[2].text = edit.edited_text or ""

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_pdf(run: AnalysisRun, db: Session, share_id: int | None = None) -> bytes:
    context = _build_context(run, db)
    result = context["result"]
    flags = context["flags"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    code_style = styles["Code"] if "Code" in styles else styles["Normal"]
    story = []

    story.append(Paragraph("QI Stat Studio Report", styles["Title"]))
    story.append(Paragraph(context["report_title"], styles["Heading1"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Methods", styles["Heading2"]))
    story.append(Paragraph(result.get("methods", ""), styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Results", styles["Heading2"]))
    story.append(Paragraph(result.get("result_summary", ""), styles["Normal"]))
    story.append(Spacer(1, 8))

    tbl_data = result.get("table", [])
    if tbl_data:
        headers = list(tbl_data[0].keys())
        rows = [[h.capitalize() for h in headers]] + [[str(r.get(h, "")) for h in headers] for r in tbl_data]
        col_w = 470 / len(headers)
        pt = Table(rows, colWidths=[col_w] * len(headers))
        pt.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(pt)
        story.append(Spacer(1, 8))

    fig_b64 = result.get("figure_base64")
    if fig_b64:
        img_data = base64.b64decode(fig_b64)
        story.append(RLImage(io.BytesIO(img_data), width=400, height=200))
        story.append(Spacer(1, 4))
        if context["caption"]:
            story.append(Paragraph(context["caption"], styles["Normal"]))
            story.append(Spacer(1, 8))

    story.append(Paragraph("Interpretation", styles["Heading2"]))
    story.append(Paragraph(context["interpretation"] or "[Resident interpretation pending]", styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Limitations", styles["Heading2"]))
    if flags:
        for f in flags:
            story.append(Paragraph(f"• {f.get('msg') or f.get('message') or str(f)}", styles["Normal"]))
    else:
        story.append(Paragraph("No data quality issues flagged.", styles["Normal"]))
    story.append(Spacer(1, 8))

    if run.code_r:
        story.append(Paragraph("Statistical Code Supplement (R)", styles["Heading2"]))
        story.append(Paragraph(run.code_r, code_style))
        story.append(Spacer(1, 8))
    if run.code_spss:
        story.append(Paragraph("Statistical Code Supplement (SPSS)", styles["Heading2"]))
        story.append(Paragraph(run.code_spss, code_style))
        story.append(Spacer(1, 8))
    if run.code_sas:
        story.append(Paragraph("Statistical Code Supplement (SAS)", styles["Heading2"]))
        story.append(Paragraph(run.code_sas, code_style))
        story.append(Spacer(1, 8))

    comments = _mentor_comments(run.project_id, db, share_id=share_id)
    if comments:
        story.append(Paragraph("Mentor Feedback", styles["Heading2"]))
        for comment in comments:
            when = comment.created_at.strftime("%Y-%m-%d %H:%M UTC") if comment.created_at else ""
            author = comment.author_name or "Mentor"
            email = f" &lt;{comment.author_email}&gt;" if comment.author_email else ""
            story.append(Paragraph(f"{when} — {author}{email}: {comment.text}", styles["Normal"]))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Audit Trail", styles["Heading2"]))
    audit_data = _base_audit_rows(run, context)
    t = Table(audit_data, colWidths=[120, 350])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    story.append(t)

    audit_entries = _audit_entries(run.project_id, db)
    if audit_entries:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Project Audit Log", styles["Heading2"]))
        audit_rows = [["Timestamp", "Action", "Metadata"]] + [
            [
                entry.timestamp.strftime("%Y-%m-%d %H:%M UTC") if entry.timestamp else "",
                entry.action or "",
                _audit_metadata_summary(entry.metadata_json),
            ]
            for entry in audit_entries
        ]
        at = Table(audit_rows, colWidths=[130, 120, 220])
        at.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(at)

    edits = list(context["edits"].values())
    if edits:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Resident Edits", styles["Heading2"]))
        edit_data = [["Field", "Original Text", "Edited Text"]] + [
            [edit.field or "", edit.original_text or "", edit.edited_text or ""] for edit in edits
        ]
        et = Table(edit_data, colWidths=[80, 220, 170])
        et.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(et)

    doc.build(story)
    return buf.getvalue()


@router.get("/{run_id}/docx")
def download_docx(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = _get_run_or_404(run_id, db)
    _require_run_access(run, db, user)
    content = _build_docx(run, db)
    log_action(db, run.project_id, "report_downloaded", {"run_id": run.id, "format": "docx"})
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=qi_report_{run_id}.docx"},
    )


@router.get("/{run_id}/pdf")
def download_pdf(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = _get_run_or_404(run_id, db)
    _require_run_access(run, db, user)
    content = _build_pdf(run, db)
    log_action(db, run.project_id, "report_downloaded", {"run_id": run.id, "format": "pdf"})
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=qi_report_{run_id}.pdf"},
    )
