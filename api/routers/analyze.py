import json
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api.models_api import AnalysisRequest

router = APIRouter(prefix="/analyze", tags=["analyze"])

_ALL = ["descriptive_summary", "before_after_mean", "before_after_pct",
        "run_chart", "p_chart", "u_c_chart"]

_DESCRIPTIONS = {
    "descriptive_summary": "Summarizes counts, averages, and percentages — best when describing one time period or group.",
    "before_after_mean": "Compares an average value between two periods using a t-test or Wilcoxon test.",
    "before_after_pct": "Compares a proportion between two periods using chi-square or Fisher's exact test.",
    "run_chart": "Line chart over time with median and run signals — good for <12 time points.",
    "p_chart": "Control chart for proportions with 3-sigma control limits — best with ≥12 time points.",
    "u_c_chart": "Control chart for rates or counts with 3-sigma control limits — best with ≥12 time points.",
}


def select_template(answers: dict) -> List[str]:
    # Substring matching — intake stores full option text like
    # "An average or median value", "No — I'm just describing one time period"
    q2 = str(answers.get("q2", "")).lower()
    q3 = str(answers.get("q3", "")).lower()
    q4 = str(answers.get("q4", "")).lower()
    q6 = int(answers.get("q6", 0) or 0)

    is_time = "time" in q4 or "over time" in q4
    is_groups = "group" in q4 or "comparing" in q4
    is_no_comparison = q3.startswith("no") or "one time period" in q3 or "describing" in q3
    is_yes_comparison = q3.startswith("yes") or "before and after" in q3
    is_pct = "percent" in q2 or "proportion" in q2
    is_rate = "rate" in q2
    is_avg = "average" in q2 or "median" in q2

    if is_no_comparison and is_groups:
        top = "descriptive_summary"
    elif is_time and is_pct and q6 >= 12:
        top = "p_chart"
    elif is_time and is_rate and q6 >= 12:
        top = "u_c_chart"
    elif is_time and q6 < 12:
        top = "run_chart"
    elif is_yes_comparison and is_avg:
        top = "before_after_mean"
    elif is_yes_comparison and is_pct:
        top = "before_after_pct"
    else:
        top = "run_chart"  # ponytail: conservative default; covers "unsure" and "something else"

    rest = [t for t in _ALL if t != top]
    return [top] + rest[:2]


@router.get("/{project_id}/recommend")
def recommend(project_id: int, db: Session = Depends(get_db)):
    from api.models_db import IntakeAnswer
    rows = db.query(IntakeAnswer).filter(IntakeAnswer.project_id == project_id).all()
    answers = {r.question_key: r.answer for r in rows}
    ranked = select_template(answers)
    return [{"template": t, "description": _DESCRIPTIONS[t],
             "recommended": i == 0} for i, t in enumerate(ranked)]


@router.post("/run")
def run_analysis(body: AnalysisRequest, db: Session = Depends(get_db)):
    from api.models_db import Upload, AnalysisRun, FailureLog, IntakeAnswer
    from api.templates.registry import TEMPLATE_REGISTRY
    from api.config import settings
    import io
    import pandas as pd

    upload = db.query(Upload).get(body.upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if body.template not in TEMPLATE_REGISTRY:
        raise HTTPException(400, f"Unknown template: {body.template}")
    try:
        raw = settings.fernet.decrypt(open(upload.encrypted_path, "rb").read())
        df = pd.read_csv(io.BytesIO(raw))
        result = TEMPLATE_REGISTRY[body.template](df, body.parameters)
        from api.templates.codegen import generate_r_code
        code_r = generate_r_code(body.template, body.parameters)

        # Read Q9 to determine code language preference
        q9_row = db.query(IntakeAnswer).filter(
            IntakeAnswer.project_id == body.project_id,
            IntakeAnswer.question_key == "q9"
        ).first()
        q9 = (q9_row.answer or "").lower() if q9_row else "r"

        code_spss = ""
        code_sas = ""
        if "spss" in q9 or "sas" in q9 or "all" in q9:
            code_spss = "# SPSS/SAS export coming in Phase 3"
            code_sas = "# SPSS/SAS export coming in Phase 3"

        run = AnalysisRun(
            project_id=body.project_id, template=body.template,
            parameters=json.dumps(body.parameters),
            result_json=json.dumps({k: v for k, v in result.items() if k != "figure_base64"}),
            code_r=code_r, code_spss=code_spss, code_sas=code_sas
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return {**result, "run_id": run.id}
    except Exception as e:
        db.add(FailureLog(project_id=body.project_id, error_type=str(type(e).__name__),
                          template=body.template))
        db.commit()
        raise HTTPException(500, str(e))
