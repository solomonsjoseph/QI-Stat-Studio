from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.audit import log_action
from api.analysis_schemas import validate_template_parameters
from api.analysis_validation import validate_analysis_inputs
from api.auth import get_current_user, require_project_owner
from api.database import get_db
from api.models_api import AnalysisRequest
from api.models_db import Project, User
from api.upload_utils import load_upload_dataframe

router = APIRouter(prefix="/analyze", tags=["analyze"])

_Q5_FREQ = {
    "daily": "D",
    "weekly": "W-MON",
    "monthly": "ME",
    "one row per patient": "D",
}


def q5_to_freq(q5: str) -> str:
    """Map Q5 time-unit answer to a pandas resample frequency string."""
    return _Q5_FREQ.get(q5.strip().lower(), "ME")


_ALL = ["descriptive_summary", "before_after_mean", "before_after_pct", "run_chart", "p_chart", "u_c_chart"]

_DESCRIPTIONS = {
    "descriptive_summary": "Summarizes counts, averages, and percentages — best when describing one time period or group.",
    "before_after_mean": "Compares an average value between two periods using a t-test or Wilcoxon test.",
    "before_after_pct": "Compares a proportion between two periods using chi-square or Fisher's exact test.",
    "run_chart": "Line chart over time with median and run signals — good for <12 time points.",
    "p_chart": "Control chart for proportions with 3-sigma control limits — best with ≥12 time points.",
    "u_c_chart": "Control chart for rates or counts with 3-sigma control limits — best with ≥12 time points.",
}


def select_template(answers: dict) -> List[str]:
    q2 = str(answers.get("q2", "")).lower()
    q3 = str(answers.get("q3", "")).lower()
    q4 = str(answers.get("q4", "")).lower()
    q6 = int(answers.get("q6", 0) or 0)

    is_time = ("time" in q4 and "one point in time" not in q4) or "both" in q4
    is_groups = "group" in q4 or "comparing" in q4
    is_no_comparison = q3.startswith("no") or "one time period" in q3 or "describing" in q3
    is_yes_comparison = q3.startswith("yes") or "before and after" in q3
    is_multi_phase = "more than two" in q3 or "phases" in q3
    is_pct = "percent" in q2 or "proportion" in q2 or "yes/no" in q2
    is_rate = "rate" in q2
    is_count = "count" in q2
    is_avg = "average" in q2 or "median" in q2

    if is_multi_phase and not is_time:
        top = "descriptive_summary"
    elif is_multi_phase:
        top = "run_chart"
    elif is_no_comparison and is_groups:
        top = "descriptive_summary"
    elif is_time and is_pct and q6 >= 12:
        top = "p_chart"
    elif is_time and (is_rate or is_count) and q6 >= 12:
        top = "u_c_chart"
    elif is_time and q6 < 12:
        top = "run_chart"
    elif is_yes_comparison and is_avg:
        top = "before_after_mean"
    elif is_yes_comparison and is_pct:
        top = "before_after_pct"
    else:
        top = "run_chart"

    rest = [t for t in _ALL if t != top]
    return [top] + rest[:2]


@router.get("/{project_id}/recommend")
def recommend(project_id: int, db: Session = Depends(get_db), project: Project = Depends(require_project_owner)):
    from api.models_db import IntakeAnswer

    rows = db.query(IntakeAnswer).filter(IntakeAnswer.project_id == project_id).all()
    answers = {r.question_key: r.answer for r in rows}
    ranked = select_template(answers)
    return [{"template": t, "description": _DESCRIPTIONS[t], "recommended": i == 0} for i, t in enumerate(ranked)]


def _bad_analysis_request(message: str, field_errors: dict[str, list[str]] | None = None) -> HTTPException:
    return HTTPException(status_code=400, detail={"message": message, "field_errors": field_errors or {}})


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


@router.post("/run")
def run_analysis(body: AnalysisRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from api.models_db import AnalysisRun, IntakeAnswer, Upload
    from api.templates.registry import TEMPLATE_REGISTRY

    upload = db.get(Upload, body.upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.project_id != body.project_id:
        raise HTTPException(403, "Upload does not belong to project")
    project = db.get(Project, body.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if user.role != "admin" and project.owner_user_id != user.id:
        raise HTTPException(403, "Project access denied")
    if upload.status != "active":
        raise HTTPException(400, "Upload is not active")
    if body.template not in TEMPLATE_REGISTRY:
        raise HTTPException(400, "Unknown analysis template")
    _OUTCOME_COL_KEY = {
        "before_after_mean": "value_col",
        "before_after_pct": "outcome_col",
        "run_chart": "value_col",
        "p_chart": "numerator_col",
        "u_c_chart": "count_col",
    }
    df = load_upload_dataframe(upload)


    params, field_errors = validate_template_parameters(body.template, body.parameters, df.columns)
    if field_errors:
        raise _bad_analysis_request("Invalid analysis parameters", field_errors)
    assert params is not None
    if body.template in ("run_chart", "p_chart", "u_c_chart") and "freq" not in params:
        q5_row = db.query(IntakeAnswer).filter(IntakeAnswer.project_id == body.project_id, IntakeAnswer.question_key == "q5").first()
        if q5_row:
            params["freq"] = q5_to_freq(q5_row.answer or "")

    outcome_key = _OUTCOME_COL_KEY.get(body.template)
    if outcome_key:
        col = params.get(outcome_key)
        if col and col in df.columns:
            pct_missing = df[col].isna().mean() * 100
            if pct_missing > 30:
                raise HTTPException(
                    400,
                    f"Column '{col}' is {pct_missing:.1f}% missing. Analysis requires <=30% missing in the selected outcome column. Choose a different outcome column or upload corrected data; warning acknowledgement does not override this safety check.",
                )

    precondition_errors = validate_analysis_inputs(body.template, df, params)
    if precondition_errors:
        raise _bad_analysis_request(precondition_errors[0], {"parameters": precondition_errors})

    try:
        result = TEMPLATE_REGISTRY[body.template](df, params)
        result = _json_safe(result)
        from api.templates.codegen import generate_r_code, generate_sas_code, generate_spss_code

        code_r = generate_r_code(body.template, params, result)
        q9_row = db.query(IntakeAnswer).filter(IntakeAnswer.project_id == body.project_id, IntakeAnswer.question_key == "q9").first()
        q9 = (q9_row.answer or "").lower() if q9_row else "r"
        code_spss = generate_spss_code(body.template, params, result) if "spss" in q9 or "all" in q9 else ""
        code_sas = generate_sas_code(body.template, params, result) if "sas" in q9 or "all" in q9 else ""
        run = AnalysisRun(
            project_id=body.project_id,
            upload_id=body.upload_id,
            template=body.template,
            parameters=json.dumps(params),
            result_json=json.dumps(result),
            created_at=datetime.utcnow(),
            code_r=code_r,
            code_spss=code_spss,
            code_sas=code_sas,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        log_action(db, body.project_id, "analysis_run_created", {"run_id": run.id, "upload_id": body.upload_id, "template": body.template})
        return {**result, "run_id": run.id}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise
