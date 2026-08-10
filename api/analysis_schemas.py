from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError


class AnalysisParamsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DescriptiveParams(AnalysisParamsBase):
    group_col: Optional[str] = None
    value_cols: list[str]


class BeforeAfterMeanParams(AnalysisParamsBase):
    group_col: str
    value_col: str
    pre_val: str
    post_val: str
    intervention_label: str = "Intervention"


class BeforeAfterPctParams(AnalysisParamsBase):
    group_col: str
    outcome_col: str
    pre_val: str
    post_val: str


class RunChartParams(AnalysisParamsBase):
    date_col: str
    value_col: str
    intervention_date: Optional[str] = None
    freq: Optional[str] = None
    design_note: Optional[str] = None


class PChartParams(AnalysisParamsBase):
    date_col: str
    numerator_col: str
    denominator_col: Optional[str] = None
    intervention_date: Optional[str] = None
    freq: Optional[str] = None


class UCChartParams(AnalysisParamsBase):
    date_col: str
    count_col: str
    denominator_col: Optional[str] = None
    intervention_date: Optional[str] = None
    freq: Optional[str] = None


TEMPLATE_PARAM_MODELS: dict[str, type[AnalysisParamsBase]] = {
    "descriptive_summary": DescriptiveParams,
    "before_after_mean": BeforeAfterMeanParams,
    "before_after_pct": BeforeAfterPctParams,
    "run_chart": RunChartParams,
    "p_chart": PChartParams,
    "u_c_chart": UCChartParams,
}

_TEMPLATE_COLUMN_FIELDS: dict[str, dict[str, bool]] = {
    "descriptive_summary": {"group_col": False, "value_cols": True},
    "before_after_mean": {"group_col": True, "value_col": True},
    "before_after_pct": {"group_col": True, "outcome_col": True},
    "run_chart": {"date_col": True, "value_col": True},
    "p_chart": {"date_col": True, "numerator_col": True, "denominator_col": False},
    "u_c_chart": {"date_col": True, "count_col": True, "denominator_col": False},
}


def normalize_parameter_payload(template: str, parameters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters or {})
    if template == "descriptive_summary" and isinstance(normalized.get("value_cols"), str):
        normalized["value_cols"] = [col.strip() for col in normalized["value_cols"].split(",") if col.strip()]
    return normalized


def validate_template_parameters(template: str, parameters: dict[str, Any], dataframe_columns) -> tuple[dict[str, Any] | None, dict[str, list[str]]]:
    model = TEMPLATE_PARAM_MODELS.get(template)
    if model is None:
        return None, {"template": [f"Unknown template: {template}"]}

    normalized = normalize_parameter_payload(template, parameters)
    try:
        validated = model.model_validate(normalized).model_dump(exclude_none=True)
    except ValidationError as exc:
        field_errors: dict[str, list[str]] = {}
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", []) if part != "parameters") or "parameters"
            field_errors.setdefault(loc, []).append(str(err.get("msg", "Invalid value")))
        return None, field_errors

    existing_columns = {str(col) for col in dataframe_columns}
    field_errors: dict[str, list[str]] = {}
    for field, required in _TEMPLATE_COLUMN_FIELDS.get(template, {}).items():
        value = validated.get(field)
        if not value:
            if required:
                field_errors.setdefault(field, []).append("Field required")
            continue
        if isinstance(value, list):
            missing = [col for col in value if col not in existing_columns]
            if missing:
                field_errors.setdefault(field, []).extend(
                    f"Column '{col}' does not exist in the uploaded dataset" for col in missing
                )
        elif str(value) not in existing_columns:
            field_errors.setdefault(field, []).append(f"Column '{value}' does not exist in the uploaded dataset")

    return (None, field_errors) if field_errors else (validated, {})
