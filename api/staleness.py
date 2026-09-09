from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from api.models_db import Project, Upload


def _parse_json(raw: str | None, fallback: Any):
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def compute_inputs_fingerprint(project: Project, upload: Upload | None) -> str:
    """Compute sha256 over description, upload checksum, dictionary, col_types, and key design fields."""
    desc = project.description or ""
    chk = (upload.checksum_sha256 if upload else "") or ""
    dict_text = (upload.dictionary_text if upload else "") or ""
    col_types = (upload.col_types if upload else "") or ""

    design_dict = _parse_json(project.ai_project_design, {})
    po_col = design_dict.get("primary_outcome", {}).get("column") or ""
    start_date = design_dict.get("intervention", {}).get("start_date") or ""
    granularity = design_dict.get("time_structure", {}).get("granularity") or ""
    group_col = design_dict.get("group_column") or ""

    components = [
        desc,
        chk,
        dict_text,
        col_types,
        str(po_col),
        str(start_date),
        str(granularity),
        str(group_col),
    ]
    raw = "|".join(components).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def check_and_apply_inputs_fingerprint(project: Project, upload: Upload | None, db: Session) -> bool:
    """Check if inputs fingerprint changed; if so, update fingerprint and mark downstream state stale."""
    new_fp = compute_inputs_fingerprint(project, upload)
    old_fp = project.inputs_fingerprint
    if old_fp is None:
        project.inputs_fingerprint = new_fp
        return False
    if new_fp != old_fp:
        project.inputs_fingerprint = new_fp
        # Mark plan stale
        plan = _parse_json(project.ai_analysis_plan, {})
        if plan:
            plan["stale"] = True
            project.ai_analysis_plan = json.dumps(plan)
        # Clear collection notes
        project.data_collection_notes = None
        # Mark clarification state stale
        clarify = _parse_json(project.ai_clarification_state, {})
        if clarify:
            clarify["stale"] = True
            project.ai_clarification_state = json.dumps(clarify)
        return True
    return False
