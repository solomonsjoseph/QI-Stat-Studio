from __future__ import annotations

import logging

import base64
import io
import json
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from api.audit import log_action, sanitize_audit_metadata
from api.auth import get_current_user
from api.data_changes import build_data_changes, data_change_lines
from api.database import get_db
from api.models_api import ProjectDesign
from api.models_db import AnalysisRun, AuditLog, EditHistory, MentorComment, MentorShare, Project, Upload, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report", tags=["report"])
_REPORT_EDIT_FIELDS = {"title", "caption", "interpretation"}


def _esc(text: Any) -> str:
    """Escape text before handing it to ReportLab's Paragraph, which parses a small XML
    markup subset. Unescaped resident text (e.g. containing '<b>' or '&') can otherwise
    raise a ValueError and break PDF generation."""
    return _xml_escape(str(text))


_HEADER_WORDS = {"ci": "CI", "sd": "SD", "n": "N", "pct": "%"}


def _header_text(key: str) -> str:
    text = " ".join(_HEADER_WORDS.get(w.lower(), w) for w in str(key).split("_"))
    return text[:1].upper() + text[1:]


# Same names the app shows (web/src/templateLabels.js), so the report reads like the screens.
_TEMPLATE_TITLES = {
    "descriptive_summary": "Descriptive Summary",
    "before_after_mean": "Before/After: Mean",
    "before_after_pct": "Before/After: Proportion",
    "before_after_paired": "Before/After: Paired",
    "run_chart": "Run Chart",
    "p_chart": "p-Chart",
    "u_c_chart": "u/c-Chart",
}


def _template_title(template: str | None) -> str:
    return _TEMPLATE_TITLES.get(template or "", (template or "Analysis").replace("_", " ").title())


def _pdf_styles():
    """Default styles, with headings kept on the same page as what follows them."""
    styles = getSampleStyleSheet()
    styles["Heading1"].alignment = TA_CENTER  # the report title is the only Heading1 in the PDF
    for name in ("Heading1", "Heading2", "Heading3"):
        styles[name].keepWithNext = 1
    return styles


def _center(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return paragraph


_PDF_WIDTH = letter[0] - 2 * 72  # SimpleDocTemplate default margins: the usable width in points
_PDF_MIN_COL = 34


def _pdf_table(rows: list[list[Any]], header_bg: Any = colors.lightgrey, widths: list[float] | None = None) -> Table:
    """A table that always fits the page. Every cell is a wrapping Paragraph, so long text and many
    columns wrap instead of printing over the next cell, and column widths follow the content."""
    ncols = max(len(r) for r in rows)
    size = 9 if ncols <= 5 else 8 if ncols <= 8 else 7
    cell = ParagraphStyle("cell", parent=getSampleStyleSheet()["Normal"], fontSize=size, leading=size + 2)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    data = [[Paragraph(_esc(c), head if i == 0 else cell) for c in r] for i, r in enumerate(rows)]
    if widths is None:
        # Weight by the longest word and the typical length, so ids stay whole and prose gets the room.
        weights = []
        for j in range(ncols):
            col = [str(r[j]) if j < len(r) else "" for r in rows]
            longest_word = max((len(w) for c in col for w in c.split()), default=1)
            typical = sum(len(c) for c in col) / len(col)
            weights.append(max(longest_word, min(typical, 60), 4))
        total = sum(weights)
        widths = [max(_PDF_MIN_COL, _PDF_WIDTH * w / total) for w in weights]
    scale = min(1.0, _PDF_WIDTH / sum(widths))
    table = Table(data, colWidths=[w * scale for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _pdf_image(png: bytes, max_w: float = _PDF_WIDTH, max_h: float = 320) -> RLImage:
    """The figure at its own aspect ratio, never wider than the page."""
    w, h = ImageReader(io.BytesIO(png)).getSize()
    scale = min(max_w / w, max_h / h, 1.0)
    return RLImage(io.BytesIO(png), width=w * scale, height=h * scale)


def _cell_text(value: Any) -> str:
    """Render a result-table cell value for DOCX/PDF export. Statistics such as
    confidence intervals are legitimately omitted (None) for small groups; show an
    em dash instead of the literal string 'None' in the resident's report."""
    return "n/a" if value is None else str(value)


def _safe_json(raw: str | None, fallback: Any):
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _require_project_report_access(project_id: int, db: Session, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if user.role != "admin" and project.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Project access denied")
    return project


def _latest_edits(project_id: int, db: Session, run_id: int | None = None) -> dict[str, EditHistory]:
    query = db.query(EditHistory).filter(EditHistory.project_id == project_id, EditHistory.field.in_(_REPORT_EDIT_FIELDS))
    if run_id is not None:
        query = query.filter((EditHistory.run_id == run_id) | EditHistory.run_id.is_(None))
    else:
        query = query.filter(EditHistory.run_id.is_(None))
    rows = query.order_by(EditHistory.id.desc()).all()
    latest: dict[str, EditHistory] = {}
    for row in rows:
        if row.field not in latest or (row.run_id == run_id and latest[row.field].run_id != run_id):
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

    edits = _latest_edits(run.project_id, db, run_id=run.id)
    title_edit = edits.get("title")
    caption_edit = edits.get("caption")
    interpretation_edit = edits.get("interpretation")

    report_title = (
        title_edit.edited_text
        if title_edit and title_edit.edited_text
        else (project.title if project and project.title else f"Project {run.project_id}")
    )
    caption = caption_edit.edited_text if caption_edit and caption_edit.edited_text else ""
    if project and project.ai_project_design:
        try:
            design = ProjectDesign.model_validate(json.loads(project.ai_project_design or "{}"))
            if design.intervention.present and design.intervention.start_date:
                desc = design.intervention.description or "Intervention"
                intervention_note = f"Intervention: {desc} ({design.intervention.start_date})"
                caption = f"{caption} {intervention_note}".strip()
        except Exception as exc:
            logger.warning("intervention_note_failed run_id=%s error_type=%s", run.id, type(exc).__name__)
    interpretation = (
        interpretation_edit.edited_text
        if interpretation_edit and interpretation_edit.edited_text
        else (result.get("ai_interpretation") or result.get("interpretation", ""))
    )
    result = dict(result)
    if interpretation:
        result["interpretation"] = interpretation

    data_changes = result.get("data_changes")
    if not data_changes and "data_changes" not in result:
        try:  # older run without a snapshot: compute from the current handoff
            data_changes = build_data_changes(upload)
            if data_changes:
                data_changes = dict(data_changes, fallback=True)
        except Exception:
            data_changes = None

    return {
        "data_changes": data_changes,
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


def run_hydration_dict(run: AnalysisRun, db: Session, *, raw_caption: bool = False) -> dict[str, Any]:
    """Flat, frontend/mentor-consumable view of one run: `run_id`/`template` plus the
    result fields spread at the top level, edit-resolved `caption`/`interpretation`
    (as `ai_interpretation`), and code supplements. Shared by `resume_project` and
    `mentor_view` so both surfaces render from the same shape as a fresh `run-plan`
    response.

    `raw_caption=True` (used for the resident-editable resume/edit surface) returns the
    un-augmented `EditHistory` caption text, not `_build_context`'s report-rendering
    caption (which appends an "Intervention: ..." note) -- reusing the augmented text as
    an edit's `original_text` would re-append the note on every save/reload cycle.
    """
    ctx = _build_context(run, db)
    res = ctx["result"]
    if raw_caption:
        caption_edit = ctx["edits"].get("caption")
        caption = caption_edit.edited_text if caption_edit and caption_edit.edited_text else ""
    else:
        caption = ctx.get("caption", "")
    return {
        "run_id": run.id,
        "template": run.template,
        "parameters": ctx["params"],
        "methods": res.get("methods", ""),
        "result_summary": res.get("result_summary", ""),
        "ai_interpretation": ctx.get("interpretation", ""),
        "table": res.get("table", []),
        "figure_base64": res.get("figure_base64"),
        "caption": caption,
        "code_r": run.code_r or "",
        "code_spss": run.code_spss or "",
        "code_sas": run.code_sas or "",
        "created_at": run.created_at,
        **{k: v for k, v in res.items() if k not in {
            "methods", "result_summary", "interpretation", "ai_interpretation", "table", "figure_base64",
        }},
    }


def _build_project_context(project_id: int, db: Session) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    upload = (
        db.query(Upload)
        .filter(Upload.project_id == project_id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )
    all_runs = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.created_at.asc(), AnalysisRun.id.asc())
        .all()
    )
    if upload:
        upload_runs = [r for r in all_runs if r.upload_id == upload.id]
        runs = upload_runs if upload_runs else all_runs
    else:
        runs = all_runs

    runs_context = [_build_context(r, db) for r in runs]

    plan_dict = _safe_json(project.ai_analysis_plan, {})
    narrative = plan_dict.get("narrative", {})
    limitations = narrative.get("limitations", [])
    abstract_draft = narrative.get("abstract_draft", "")

    title_edits = _latest_edits(project_id, db, run_id=None)
    title_edit = title_edits.get("title")
    report_title = (
        title_edit.edited_text
        if title_edit and title_edit.edited_text
        else (project.title or f"Project {project_id}")
    )

    return {
        "project": project,
        "upload": upload,
        "runs": runs_context,
        "raw_runs": runs,
        "report_title": report_title,
        "limitations": limitations,
        "abstract_draft": abstract_draft,
    }


def _changes_title(*dcs: Any) -> str:
    if any(isinstance(d, dict) and d.get("fallback") for d in dcs):
        return "Data changes (current handoff at export time)"
    return "Data changes applied"


def _project_change_lines(ctx: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for run_ctx in ctx["runs"]:
        for line in data_change_lines(run_ctx.get("data_changes")):
            if line not in lines:
                lines.append(line)
    return lines


def _build_project_docx(project_id: int, db: Session, share_id: int | None = None) -> bytes:
    ctx = _build_project_context(project_id, db)
    upload = ctx["upload"]

    doc = Document()
    _center(doc.add_heading("QI Stat Studio Report", 0))
    _center(doc.add_heading(ctx["report_title"], 1))

    if ctx["abstract_draft"]:
        doc.add_heading("Abstract", 1)
        doc.add_paragraph(ctx["abstract_draft"])

    doc.add_heading("Methods", 1)
    for run_ctx in ctx["runs"]:
        methods_text = run_ctx["result"].get("methods")
        if methods_text:
            doc.add_paragraph(methods_text)
    if not ctx["runs"]:
        doc.add_paragraph("No analysis runs available.")

    for run, run_ctx in zip(ctx["raw_runs"], ctx["runs"]):  # same order; result_json has no run_id to look up
        template_name = _template_title(run.template if run else None)
        doc.add_heading(template_name, 1)

        res = run_ctx["result"]
        if res.get("result_summary"):
            doc.add_heading("Results Summary", 2)
            doc.add_paragraph(res["result_summary"])

        tbl_data = res.get("table", [])
        if tbl_data:
            headers = list(tbl_data[0].keys())
            rt = doc.add_table(rows=1 + len(tbl_data), cols=len(headers))
            rt.style = "Table Grid"
            for j, h in enumerate(headers):
                rt.rows[0].cells[j].text = _header_text(h)
            for i, row in enumerate(tbl_data, 1):
                for j, h in enumerate(headers):
                    rt.rows[i].cells[j].text = _cell_text(row.get(h, ""))

        fig_b64 = res.get("figure_base64")
        if fig_b64:
            try:
                img_data = base64.b64decode(fig_b64)
                doc.add_picture(io.BytesIO(img_data), width=Inches(5.5))
            except Exception as exc:
                logger.warning("figure_not_rendered format=docx error_type=%s", type(exc).__name__)
                doc.add_paragraph("[The figure could not be placed in this report.]")
            if run_ctx.get("caption"):
                doc.add_paragraph(run_ctx["caption"])

        interp = run_ctx.get("interpretation") or res.get("ai_interpretation")
        if interp:
            doc.add_heading("Interpretation", 2)
            doc.add_paragraph(interp)

    doc.add_heading("Limitations", 1)
    all_limitations = list(ctx["limitations"])
    for r in ctx["runs"]:
        for lim in (r.get("result") or {}).get("limitations") or []:
            if lim not in all_limitations:
                all_limitations.append(lim)
    if upload:
        flags = _safe_json(upload.acknowledged_flags, [])
        for f in flags:
            msg = f.get("msg") or f.get("message") or str(f)
            if msg not in all_limitations:
                all_limitations.append(msg)
    if all_limitations:
        for lim in all_limitations:
            doc.add_paragraph(f"• {lim}", style="List Bullet")
    else:
        doc.add_paragraph("No data quality issues were flagged for this dataset.")
    changes = _project_change_lines(ctx)
    if changes:
        doc.add_heading(_changes_title(*[r.get("data_changes") for r in ctx["runs"]]), 2)
        for line in changes:
            doc.add_paragraph(f"• {line}", style="List Bullet")
    # Code supplements
    code_r_list = [r.code_r for r in ctx["raw_runs"] if r.code_r]
    code_spss_list = [r.code_spss for r in ctx["raw_runs"] if r.code_spss]
    code_sas_list = [r.code_sas for r in ctx["raw_runs"] if r.code_sas]

    if code_r_list:
        doc.add_heading("Statistical Code Supplement (R)", 1)
        doc.add_paragraph("\n\n".join(code_r_list), style="No Spacing")
    if code_spss_list:
        doc.add_heading("Statistical Code Supplement (SPSS)", 1)
        doc.add_paragraph("\n\n".join(code_spss_list), style="No Spacing")
    if code_sas_list:
        doc.add_heading("Statistical Code Supplement (SAS)", 1)
        doc.add_paragraph("\n\n".join(code_sas_list), style="No Spacing")

    doc.add_heading("Audit Trail", 1)
    for run, run_ctx in zip(ctx["raw_runs"], ctx["runs"]):
        audit_rows = _base_audit_rows(run, run_ctx)
        tbl = doc.add_table(rows=len(audit_rows), cols=2)
        tbl.style = "Table Grid"
        for i, (key, value) in enumerate(audit_rows):
            tbl.rows[i].cells[0].text = key
            tbl.rows[i].cells[1].text = str(value)
    audit_entries = _audit_entries(project_id, db)
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

    edits = (
        db.query(EditHistory)
        .filter(EditHistory.project_id == project_id)
        .order_by(EditHistory.timestamp.asc(), EditHistory.id.asc())
        .all()
    )
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

    _add_mentor_review_docx(doc, _mentor_review_blocks(project_id, db, share_id))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_project_pdf(project_id: int, db: Session, share_id: int | None = None) -> bytes:
    ctx = _build_project_context(project_id, db)
    upload = ctx["upload"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = _pdf_styles()
    code_style = styles["Code"] if "Code" in styles else styles["Normal"]
    story = []

    story.append(Paragraph("QI Stat Studio Report", styles["Title"]))
    story.append(Paragraph(_esc(ctx["report_title"]), styles["Heading1"]))
    story.append(Spacer(1, 12))

    if ctx["abstract_draft"]:
        story.append(Paragraph("Abstract", styles["Heading2"]))
        story.append(Paragraph(_esc(ctx["abstract_draft"]), styles["Normal"]))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Methods", styles["Heading2"]))
    for run_ctx in ctx["runs"]:
        methods_text = run_ctx["result"].get("methods")
        if methods_text:
            story.append(Paragraph(_esc(methods_text), styles["Normal"]))
            story.append(Spacer(1, 6))
    if not ctx["runs"]:
        story.append(Paragraph("No analysis methods available.", styles["Normal"]))
    story.append(Spacer(1, 8))

    for run, run_ctx in zip(ctx["raw_runs"], ctx["runs"]):  # same order; result_json has no run_id to look up
        template_name = _template_title(run.template if run else None)
        story.append(Paragraph(template_name, styles["Heading2"]))

        res = run_ctx["result"]
        if res.get("result_summary"):
            story.append(Paragraph(_esc(res["result_summary"]), styles["Normal"]))
            story.append(Spacer(1, 6))

        tbl_data = res.get("table", [])
        if tbl_data:
            headers = list(tbl_data[0].keys())
            rows = [[_header_text(h) for h in headers]] + [[_cell_text(r.get(h, "")) for h in headers] for r in tbl_data]
            pt = _pdf_table(rows)
            story.append(pt)
            story.append(Spacer(1, 8))

        fig_b64 = res.get("figure_base64")
        if fig_b64:
            try:
                img_data = base64.b64decode(fig_b64)
                story.append(_pdf_image(img_data))
                story.append(Spacer(1, 4))
            except Exception as exc:
                logger.warning("figure_not_rendered format=pdf error_type=%s", type(exc).__name__)
                story.append(Paragraph("[The figure could not be placed in this report.]", styles["Normal"]))
            if run_ctx.get("caption"):
                story.append(Paragraph(_esc(run_ctx["caption"]), styles["Normal"]))
                story.append(Spacer(1, 8))

        interp = run_ctx.get("interpretation") or res.get("ai_interpretation")
        if interp:
            story.append(Paragraph(f"<b>Interpretation:</b> {_esc(interp)}", styles["Normal"]))
            story.append(Spacer(1, 8))

    story.append(Paragraph("Limitations", styles["Heading2"]))
    all_limitations = list(ctx["limitations"])
    for r in ctx["runs"]:
        for lim in (r.get("result") or {}).get("limitations") or []:
            if lim not in all_limitations:
                all_limitations.append(lim)
    if upload:
        flags = _safe_json(upload.acknowledged_flags, [])
        for f in flags:
            msg = f.get("msg") or f.get("message") or str(f)
            if msg not in all_limitations:
                all_limitations.append(msg)
    if all_limitations:
        for lim in all_limitations:
            story.append(Paragraph(f"• {_esc(lim)}", styles["Normal"]))
    else:
        story.append(Paragraph("No data quality issues were flagged for this dataset.", styles["Normal"]))
    changes = _project_change_lines(ctx)
    if changes:
        story.append(Paragraph(_esc(_changes_title(*[r.get("data_changes") for r in ctx["runs"]])), styles["Heading3"]))
        for line in changes:
            story.append(Paragraph(f"• {_esc(line)}", styles["Normal"]))
    story.append(Spacer(1, 8))

    # Code supplements
    for run in ctx["raw_runs"]:
        if run.code_r or run.code_spss or run.code_sas:
            story.append(Paragraph(f"Code Supplement ({run.template})", styles["Heading2"]))
            if run.code_r:
                story.append(Paragraph("<b>R Code</b>", styles["Normal"]))
                for line in run.code_r.split("\n"):
                    story.append(Paragraph(_esc(line), code_style))
                story.append(Spacer(1, 4))
            if run.code_spss:
                story.append(Paragraph("<b>SPSS Code</b>", styles["Normal"]))
                for line in run.code_spss.split("\n"):
                    story.append(Paragraph(_esc(line), code_style))
                story.append(Spacer(1, 4))
            if run.code_sas:
                story.append(Paragraph("<b>SAS Code</b>", styles["Normal"]))
                for line in run.code_sas.split("\n"):
                    story.append(Paragraph(_esc(line), code_style))
                story.append(Spacer(1, 4))

    story.append(Paragraph("Audit Trail", styles["Heading2"]))
    for run, run_ctx in zip(ctx["raw_runs"], ctx["runs"]):
        audit_data = _base_audit_rows(run, run_ctx)
        t = _pdf_table(audit_data, header_bg=colors.grey, widths=[120, 348])
        story.append(t)
        story.append(Spacer(1, 4))
    audit_entries = _audit_entries(project_id, db)
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
        at = _pdf_table(audit_rows, widths=[116, 134, 218])
        story.append(at)

    edits = (
        db.query(EditHistory)
        .filter(EditHistory.project_id == project_id)
        .order_by(EditHistory.timestamp.asc(), EditHistory.id.asc())
        .all()
    )
    if edits:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Resident Edits", styles["Heading2"]))
        edit_data = [["Field", "Original Text", "Edited Text"]] + [
            [edit.field or "", edit.original_text or "", edit.edited_text or ""] for edit in edits
        ]
        et = _pdf_table(edit_data, widths=[70, 199, 199])
        story.append(et)

    _add_mentor_review_pdf(story, styles, _mentor_review_blocks(project_id, db, share_id))
    doc.build(story)
    return buf.getvalue()

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


def _stamp(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else ""


def _mentor_review_blocks(project_id: int, db: Session, share_id: int | None = None) -> list[tuple[str, str]]:
    """The mentor review as (kind, text) lines for the last section of a report: each comment, what the
    resident did about it, where it stands, then the mentor's approval."""
    blocks: list[tuple[str, str]] = []
    for comment in _mentor_comments(project_id, db, share_id=share_id):
        author = comment.author_name or "Mentor"
        email = f" <{comment.author_email}>" if comment.author_email else ""
        blocks.append(("comment", f"{_stamp(comment.created_at)}, {author}{email}: {comment.text}"))
        if comment.resident_reply:
            blocks.append(("detail", f"Resident reply ({_stamp(comment.addressed_at)}): {comment.resident_reply}"))
        if comment.resolved_at:
            status = f"Resolved by the mentor on {_stamp(comment.resolved_at)}"
        elif comment.addressed_at:
            status = f"Addressed by the resident on {_stamp(comment.addressed_at)}, waiting for the mentor"
        else:
            status = "Open"
        blocks.append(("detail", f"Status: {status}"))
    query = db.query(MentorShare).filter(
        MentorShare.project_id == project_id, MentorShare.revoked_at.is_(None), MentorShare.approved_at.isnot(None)
    )
    if share_id is not None:
        query = query.filter(MentorShare.id == share_id)
    approved = query.order_by(MentorShare.approved_at.desc()).first()
    if approved:
        note = f" {approved.approved_note}" if approved.approved_note else ""
        blocks.append(("approval", f"Mentor approval: approved by {approved.approved_by_name or 'the mentor'} on {_stamp(approved.approved_at)}.{note}"))
    return blocks


def _add_mentor_review_docx(doc: Document, blocks: list[tuple[str, str]]) -> None:
    if not blocks:
        return
    doc.add_heading("Mentor Feedback", 1)
    for kind, text in blocks:
        paragraph = doc.add_paragraph(text)
        if kind == "detail":
            paragraph.paragraph_format.left_indent = Inches(0.3)
        elif kind == "approval":
            for run in paragraph.runs:
                run.bold = True


def _add_mentor_review_pdf(story: list, styles: Any, blocks: list[tuple[str, str]]) -> None:
    if not blocks:
        return
    story.append(Paragraph("Mentor Feedback", styles["Heading2"]))
    detail = ParagraphStyle("mentor_detail", parent=styles["Normal"], leftIndent=18)
    for kind, text in blocks:
        style = detail if kind == "detail" else styles["Normal"]
        story.append(Paragraph(f"<b>{_esc(text)}</b>" if kind == "approval" else _esc(text), style))
    story.append(Spacer(1, 8))


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
    _center(doc.add_heading("QI Stat Studio Report", 0))
    _center(doc.add_heading(context["report_title"], 1))

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
            rt.rows[0].cells[j].text = _header_text(h)
        for i, row in enumerate(tbl_data, 1):
            for j, h in enumerate(headers):
                rt.rows[i].cells[j].text = _cell_text(row.get(h, ""))

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
    changes = data_change_lines(context["data_changes"])
    if changes:
        doc.add_heading(_changes_title(context["data_changes"]), 2)
        for line in changes:
            doc.add_paragraph(f"• {line}", style="List Bullet")

    if run.code_r:
        doc.add_heading("Statistical Code Supplement (R)", 1)
        doc.add_paragraph(run.code_r, style="No Spacing")
    if run.code_spss:
        doc.add_heading("Statistical Code Supplement (SPSS)", 1)
        doc.add_paragraph(run.code_spss, style="No Spacing")
    if run.code_sas:
        doc.add_heading("Statistical Code Supplement (SAS)", 1)
        doc.add_paragraph(run.code_sas, style="No Spacing")

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

    _add_mentor_review_docx(doc, _mentor_review_blocks(run.project_id, db, share_id))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_pdf(run: AnalysisRun, db: Session, share_id: int | None = None) -> bytes:
    context = _build_context(run, db)
    result = context["result"]
    flags = context["flags"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = _pdf_styles()
    code_style = styles["Code"] if "Code" in styles else styles["Normal"]
    story = []

    story.append(Paragraph("QI Stat Studio Report", styles["Title"]))
    story.append(Paragraph(_esc(context["report_title"]), styles["Heading1"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Methods", styles["Heading2"]))
    story.append(Paragraph(_esc(result.get("methods", "")), styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Results", styles["Heading2"]))
    story.append(Paragraph(_esc(result.get("result_summary", "")), styles["Normal"]))
    story.append(Spacer(1, 8))

    tbl_data = result.get("table", [])
    if tbl_data:
        headers = list(tbl_data[0].keys())
        rows = [[_header_text(h) for h in headers]] + [[_cell_text(r.get(h, "")) for h in headers] for r in tbl_data]
        pt = _pdf_table(rows)
        story.append(pt)
        story.append(Spacer(1, 8))

    fig_b64 = result.get("figure_base64")
    if fig_b64:
        img_data = base64.b64decode(fig_b64)
        story.append(_pdf_image(img_data))
        story.append(Spacer(1, 4))
        if context["caption"]:
            story.append(Paragraph(_esc(context["caption"]), styles["Normal"]))
            story.append(Spacer(1, 8))

    story.append(Paragraph("Interpretation", styles["Heading2"]))
    story.append(Paragraph(_esc(context["interpretation"] or "[Resident interpretation pending]"), styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Limitations", styles["Heading2"]))
    if flags:
        for f in flags:
            story.append(Paragraph(f"• {_esc(f.get('msg') or f.get('message') or str(f))}", styles["Normal"]))
    else:
        story.append(Paragraph("No data quality issues flagged.", styles["Normal"]))
    changes = data_change_lines(context["data_changes"])
    if changes:
        story.append(Paragraph(_esc(_changes_title(context["data_changes"])), styles["Heading3"]))
        for line in changes:
            story.append(Paragraph(f"• {_esc(line)}", styles["Normal"]))
    story.append(Spacer(1, 8))

    if run.code_r:
        story.append(Paragraph("Statistical Code Supplement (R)", styles["Heading2"]))
        story.append(Paragraph(_esc(run.code_r), code_style))
        story.append(Spacer(1, 8))
    if run.code_spss:
        story.append(Paragraph("Statistical Code Supplement (SPSS)", styles["Heading2"]))
        story.append(Paragraph(_esc(run.code_spss), code_style))
        story.append(Spacer(1, 8))
    if run.code_sas:
        story.append(Paragraph("Statistical Code Supplement (SAS)", styles["Heading2"]))
        story.append(Paragraph(_esc(run.code_sas), code_style))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Audit Trail", styles["Heading2"]))
    audit_data = _base_audit_rows(run, context)
    t = _pdf_table(audit_data, header_bg=colors.grey, widths=[120, 348])
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
        at = _pdf_table(audit_rows, widths=[116, 134, 218])
        story.append(at)

    edits = list(context["edits"].values())
    if edits:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Resident Edits", styles["Heading2"]))
        edit_data = [["Field", "Original Text", "Edited Text"]] + [
            [edit.field or "", edit.original_text or "", edit.edited_text or ""] for edit in edits
        ]
        et = _pdf_table(edit_data, widths=[70, 199, 199])
        story.append(et)

    _add_mentor_review_pdf(story, styles, _mentor_review_blocks(run.project_id, db, share_id))
    doc.build(story)
    return buf.getvalue()


@router.get("/project/{project_id}/docx")
def download_project_docx(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_project_report_access(project_id, db, user)
    content = _build_project_docx(project_id, db)
    log_action(db, project_id, "report_downloaded", {"project_id": project_id, "format": "docx"})
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=qi_project_report_{project_id}.docx"},
    )


@router.get("/project/{project_id}/pdf")
def download_project_pdf(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_project_report_access(project_id, db, user)
    content = _build_project_pdf(project_id, db)
    log_action(db, project_id, "report_downloaded", {"project_id": project_id, "format": "pdf"})
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=qi_project_report_{project_id}.pdf"},
    )
