from __future__ import annotations

import logging

import json
import math
import threading
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from api.audit import log_action, safe_diagnostic_message
from api.analysis_schemas import TEMPLATE_PARAM_MODELS, validate_template_parameters
from api.analysis_validation import validate_analysis_inputs
from api.analysis_downgrade import maybe_downgrade_control_chart
from api.auth import get_current_user, require_project_owner
from api.database import get_db
from api.models_api import (
    AnalysisRequest,
    ProjectDesign,
    RunPlanRequest,
    ValidatePlanRequest,
    ValidatePlanResponse,
)
from api.data_changes import build_data_changes
from api.plan_builder import _freq_for_proportion
from api.models_db import AnalysisRun, EditHistory, FailureLog, Project, Upload, User
from api.upload_utils import load_upload_dataframe
from api.routers.projects import _gating, advance_phase, require_phase
from api.routers.warning_groups import gating_block_message
from api.templates.registry import TEMPLATE_REGISTRY

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/analyze", tags=["analyze"])

_GRANULARITY_FREQ = {"day": "D", "week": "W", "month": "ME", "quarter": "QE"}

def _granularity_to_freq(granularity: str | None) -> str:
    return _GRANULARITY_FREQ.get(str(granularity or "").lower(), "ME")

_ALL = ["descriptive_summary", "before_after_mean", "before_after_pct", "before_after_paired", "run_chart", "p_chart", "u_c_chart"]

_DESCRIPTIONS = {
    "descriptive_summary": "Summarizes counts, averages, and percentages. Best for one time period or group.",
    "before_after_mean": "Compares an average value between two periods using a t-test or Wilcoxon test.",
    "before_after_pct": "Compares a proportion between two periods using chi-square or Fisher's exact test.",
    "before_after_paired": "Compares each subject's before and after value when the same subjects appear in both periods.",
    "run_chart": "Line chart over time with median and run signals. Useful with fewer than 12 time points.",
    "p_chart": "Control chart for proportions with 3-sigma limits. Prefer when you have 12 or more time points.",
    "u_c_chart": "Control chart for rates or counts with 3-sigma limits. Prefer when you have 12 or more time points.",
}



def _bad_analysis_request(message: str, field_errors: dict[str, list[str]] | None = None) -> HTTPException:
    return HTTPException(status_code=400, detail={"message": message, "field_errors": field_errors or {}})

_OUTCOME_COL_KEY = {
    "before_after_mean": "value_col",
    "before_after_pct": "outcome_col",
    "before_after_paired": "value_col",
    "run_chart": "value_col",
    "p_chart": "numerator_col",
    "u_c_chart": "count_col",
}


def check_plan_item(
    db: Session,
    project: Project,
    upload: Upload | None,
    df: pd.DataFrame,
    template: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Validate a planned analysis item deterministically."""
    design_dict = json.loads(project.ai_project_design or "{}") if project else {}
    design = ProjectDesign.model_validate(design_dict)

    errors: list[str] = []
    if template not in TEMPLATE_REGISTRY:
        return {
            "template": template,
            "parameters": parameters,
            "ok": False,
            "errors": [f"Unknown analysis template '{template}'"],
            "missing_params": [],
        }

    model_cls = TEMPLATE_PARAM_MODELS[template]
    required_fields = [name for name, field in model_cls.model_fields.items() if field.is_required()]
    missing_params = [f for f in required_fields if f not in parameters or parameters[f] in (None, "")]

    params = dict(parameters)
    if template in ("run_chart", "p_chart", "u_c_chart") and "freq" not in params:
        params["freq"] = _granularity_to_freq(design.time_structure.granularity)
        kind = design.primary_outcome.kind if design.primary_outcome else "unknown"
        if kind in ("proportion", "binary") and params.get("date_col") in df.columns:
            params["freq"] = _freq_for_proportion(df, params["date_col"], design.time_structure.granularity) or params["freq"]

    validated_params, field_errors = validate_template_parameters(template, params, df.columns)
    if field_errors:
        for k, errs in field_errors.items():
            errors.extend([f"{k}: {e}" for e in errs])
    if validated_params is not None:
        params = validated_params

    outcome_key = _OUTCOME_COL_KEY.get(template)
    if outcome_key:
        col = params.get(outcome_key)
        if col and col in df.columns:
            pct_missing = df[col].isna().mean() * 100
            if pct_missing > 30:
                errors.append(
                    f"Column '{col}' is {pct_missing:.1f}% missing. Analysis requires <=30% missing in the selected outcome column. "
                    "Choose a different outcome column or upload corrected data; warning acknowledgement does not override this safety check."
                )

    if not errors and not missing_params:
        precondition_errors = validate_analysis_inputs(template, df, params)
        if precondition_errors:
            errors.extend(precondition_errors)

    ok = len(errors) == 0 and len(missing_params) == 0
    return {
        "template": template,
        "parameters": params,
        "ok": ok,
        "errors": errors,
        "missing_params": missing_params,
        "field_errors": field_errors or {},
    }

def determine_feasible_templates(profile: dict[str, Any], df: pd.DataFrame) -> list[str]:
    """Return all TEMPLATE_REGISTRY keys that can potentially run given candidate roles and columns."""
    roles = profile.get("candidate_roles", {})
    num_cols = [c["name"] for c in profile.get("columns", []) if c.get("inferred_type") == "Number"]
    date_cols = roles.get("date", [])
    grp_cols = roles.get("grouping", [])
    bin_cols = roles.get("binary", [])
    den_cols = roles.get("denominator", [])
    num_cand = roles.get("numerator", [])
    pairing_cols = roles.get("pairing_id", [])

    feasible: list[str] = []
    if num_cols:
        feasible.append("descriptive_summary")
    if num_cols and grp_cols:
        feasible.append("before_after_mean")
    if (bin_cols or [c["name"] for c in profile.get("columns", []) if c.get("inferred_type") == "Category"]) and grp_cols:
        feasible.append("before_after_pct")
    if num_cols and grp_cols and pairing_cols:
        feasible.append("before_after_paired")
    if date_cols and (num_cols or bin_cols):
        feasible.append("run_chart")
    if date_cols and (bin_cols or (num_cand and den_cols)):
        feasible.append("p_chart")
    if date_cols and num_cols:
        feasible.append("u_c_chart")

    return [t for t in TEMPLATE_REGISTRY.keys() if t in feasible]


NO_DENOMINATOR_LIMITATION = (
    "No denominator was assigned, so this is a counts-only chart that assumes the same exposure every period."
)
NO_DENOMINATOR_LIMITATION_P = (
    "No denominator was assigned, so each record was counted as one case in its period."
)


REVIEWED_NO_DENOMINATOR_LIMITATION = (
    "No denominator was assigned. The resident reviewed this flag and chose to run a counts-only chart, "
    "which assumes the same exposure every period."
)
REVIEWED_NO_DENOMINATOR_LIMITATION_P = (
    "No denominator was assigned. The resident reviewed this flag and chose to run it with each record "
    "counted as one case in its period."
)


def _missing_denominator(db: Session, project_id: int, template: str, params: dict[str, Any],
                         flag_reviewed: bool = False) -> str | None:
    """Limitation text when a rate/proportion chart ran without a denominator, else None."""
    if params.get("denominator_col"):
        return None
    if template == "p_chart":
        return REVIEWED_NO_DENOMINATOR_LIMITATION_P if flag_reviewed else NO_DENOMINATOR_LIMITATION_P
    if template == "u_c_chart":
        project = db.get(Project, project_id)
        try:
            kind = json.loads(project.ai_project_design or "{}").get("primary_outcome", {}).get("kind")
        except (AttributeError, TypeError, ValueError):
            kind = None
        if kind == "rate":
            return REVIEWED_NO_DENOMINATOR_LIMITATION if flag_reviewed else NO_DENOMINATOR_LIMITATION
    return None


def execute_template(
    db: Session,
    request: Request | None,
    project_id: int,
    upload_id: int,
    df: pd.DataFrame,
    template: str,
    parameters: dict[str, Any],
    flag_reviewed: bool = False,
) -> dict[str, Any]:
    """Runs maybe_downgrade_control_chart + TEMPLATE_REGISTRY + codegen, persists one AnalysisRun."""
    from api.templates.codegen import generate_r_code, generate_sas_code, generate_spss_code

    template, df, params, downgraded_from_points = maybe_downgrade_control_chart(template, df, parameters)
    if downgraded_from_points is not None:
        params, field_errors = validate_template_parameters(template, params, df.columns)
        if field_errors:
            raise _bad_analysis_request("Invalid analysis parameters", field_errors)
        precondition_errors = validate_analysis_inputs(template, df, params)
        if precondition_errors:
            raise _bad_analysis_request(precondition_errors[0], {"parameters": precondition_errors})
    else:
        params = parameters

    try:
        result = TEMPLATE_REGISTRY[template](df, params)
        result = _json_safe(result)

        # Snapshot now so a later handoff edit cannot rewrite this run's report or scripts.
        data_changes = build_data_changes(db.get(Upload, upload_id))
        code_r = generate_r_code(template, params, result, data_changes)
        code_spss = generate_spss_code(template, params, result, data_changes)
        code_sas = generate_sas_code(template, params, result, data_changes)
        if data_changes:
            result = {**result, "data_changes": data_changes}
        missing_den = _missing_denominator(db, project_id, template, params, flag_reviewed)
        if missing_den:
            result = {**result, "limitations": [missing_den]}

        run = AnalysisRun(
            project_id=project_id,
            upload_id=upload_id,
            template=template,
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
        log_action(db, project_id, "analysis_run_created", {"run_id": run.id, "upload_id": upload_id, "template": template})
        return {**result, "run_id": run.id, "template": template}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        db.add(FailureLog(
            project_id=project_id,
            upload_id=upload_id,
            error_type=type(exc).__name__,
            template=template,
            message=safe_diagnostic_message("analysis_failed"),
            action="analysis_run",
        ))
        db.commit()
        if request is not None and hasattr(request, "state"):
            request.state.failure_logged = True
        raise


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


@router.post("/validate-plan/{project_id}", response_model=ValidatePlanResponse)
def validate_plan(
    project_id: int,
    body: ValidatePlanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if user.role != "admin" and project.owner_user_id != user.id:
        raise HTTPException(403, "Project access denied")
    require_phase(db, project, "plan")

    upload = db.get(Upload, body.upload_id)
    if not upload or upload.project_id != project_id:
        raise HTTPException(404, "Upload not found")

    df = load_upload_dataframe(upload)
    from api.dataset_profile import get_effective_profile
    profile = get_effective_profile(upload)

    items = [
        check_plan_item(db, project, upload, df, item["template"], item.get("parameters", {}))
        for item in body.analyses
    ]
    feasible = determine_feasible_templates(profile, df)
    return ValidatePlanResponse(items=items, feasible_templates=feasible)


@router.post("/run")
def run_analysis(body: AnalysisRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
    require_phase(db, project, "plan")
    if upload.status != "active":
        raise HTTPException(400, "Upload is not active")
    df = load_upload_dataframe(upload)
    check = check_plan_item(db, project, upload, df, body.template, body.parameters)
    if not check["ok"]:
        if check.get("field_errors"):
            raise _bad_analysis_request("Invalid analysis parameters", check["field_errors"])
        err_msg = check["errors"][0] if check["errors"] else f"Missing required parameters: {check['missing_params']}"
        raise _bad_analysis_request(err_msg, {"parameters": check["errors"]})
    # Gate after validation so malformed requests keep their specific error; nothing runs while blocked.
    gate = _gating(db, upload)
    if not gate.can_continue:
        raise HTTPException(status_code=409, detail={"message": "Finish data review before running the analysis: %s." % gating_block_message(gate), "required_phase": "plan"})
    return execute_template(db, request, body.project_id, body.upload_id, df, body.template, check["parameters"])


# ponytail: one lock for the whole process; per-project locks only if runs get slow enough to queue.
_RUN_PLAN_LOCK = threading.Lock()


@router.post("/run-plan/{project_id}")
def run_plan(
    project_id: int,
    body: RunPlanRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Replacing the prior runs is read-then-delete-then-insert; two overlapping requests would each keep a full set.
    with _RUN_PLAN_LOCK:
        return _run_plan(project_id, body, request, db, user)


def _run_plan(project_id: int, body: RunPlanRequest, request: Request, db: Session, user: User):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if user.role != "admin" and project.owner_user_id != user.id:
        raise HTTPException(403, "Project access denied")
    require_phase(db, project, "plan")

    upload = db.get(Upload, body.upload_id)
    if not upload or upload.project_id != project_id:
        raise HTTPException(404, "Upload not found")
    if upload.status != "active":
        raise HTTPException(400, "Upload is not active")
    plan_dict = {}
    if project.ai_analysis_plan:
        try:
            plan_dict = json.loads(project.ai_analysis_plan)
        except Exception as exc:
            logger.warning("analysis_plan_unreadable project_id=%s error_type=%s", project.id, type(exc).__name__)
    if not plan_dict.get("confirmed"):
        raise HTTPException(status_code=409, detail={"message": "Analysis plan must be explicitly confirmed before running.", "required_phase": "plan"})

    if plan_dict.get("stale"):
        raise HTTPException(status_code=409, detail={"message": "The analysis plan is stale because an upstream input changed. Re-confirm the plan before running.", "required_phase": "plan"})

    gate = _gating(db, upload)
    if not gate.can_continue:
        raise HTTPException(status_code=409, detail={"message": "Finish data review before running the analysis: %s." % gating_block_message(gate), "required_phase": "plan"})

    if not body.analyses:
        raise HTTPException(400, "analyses array cannot be empty")

    df = load_upload_dataframe(upload)

    # Carry forward edits before deleting prior AnalysisRun rows for this upload
    prior_runs = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.project_id == project_id, AnalysisRun.upload_id == body.upload_id)
        .all()
    )
    prior_edits_by_template: dict[str, list[dict[str, Any]]] = {}
    for pr in prior_runs:
        edits = db.query(EditHistory).filter(EditHistory.run_id == pr.id).all()
        if edits:
            prior_edits_by_template[pr.template] = [
                {"field": e.field, "original_text": e.original_text, "edited_text": e.edited_text}
                for e in edits
            ]
        db.delete(pr)
    db.commit()

    # Only commit the phase transition once the dataframe loaded and prior runs were
    # cleared successfully -- a failure above must not leave the project stuck at
    # "execute" with its prior runs deleted and no replacement runs created.
    advance_phase(db, project, "execute")

    runs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    reviewed_templates = {a.get("template") for a in plan_dict.get("analyses", []) if a.get("flag_reviewed")}

    for item in body.analyses:
        template = item.get("template", "")
        params = item.get("parameters", {})
        check = check_plan_item(db, project, upload, df, template, params)
        if not check["ok"]:
            failures.append({
                "template": template,
                "status": "error",
                "errors": check["errors"] or [f"Missing: {check['missing_params']}"],
            })
            continue

        try:
            res = execute_template(db, request, project_id, body.upload_id, df, template, check["parameters"],
                                   flag_reviewed=template in reviewed_templates)
            new_run_id = res["run_id"]

            # Re-attach carried-forward edits
            saved_edits = prior_edits_by_template.get(template, [])
            for se in saved_edits:
                db.add(
                    EditHistory(
                        project_id=project_id,
                        run_id=new_run_id,
                        field=se["field"],
                        original_text=se["original_text"],
                        edited_text=se["edited_text"],
                    )
                )
            if saved_edits:
                db.commit()

            runs.append({"run_id": new_run_id, "template": template, "status": "ok", **res})
        except Exception as exc:
            failures.append({
                "template": template,
                "status": "error",
                "errors": [str(exc)],
            })

    # Update project plan state
    plan_dict = {}
    if project.ai_analysis_plan:
        try:
            plan_dict = json.loads(project.ai_analysis_plan)
        except Exception as exc:
            logger.warning("analysis_plan_unreadable project_id=%s error_type=%s", project.id, type(exc).__name__)
    plan_dict["confirmed"] = True
    plan_dict["stale"] = False
    plan_dict["executed_at"] = datetime.utcnow().isoformat()
    plan_dict["executed_runs"] = [{"run_id": r["run_id"], "template": r["template"]} for r in runs]
    project.ai_analysis_plan = json.dumps(plan_dict)
    db.commit()
    advance_phase(db, project, "results")

    log_action(db, project_id, "analysis_plan_executed", {"count": len(runs), "templates": [r["template"] for r in runs]})

    return {"runs": runs, "failures": failures}
