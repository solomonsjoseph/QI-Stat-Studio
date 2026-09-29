"""Unit tests for deterministic analysis plan proposals."""

from __future__ import annotations

import pandas as pd

from api.models_api import ProjectDesign
from api.plan_builder import propose_analyses


def _design(**overrides):
    base = {
        "aim": "Reduce falls",
        "population": "Inpatients",
        "comparison": "time-series",
        "primary_outcome": {
            "label": "Fall rate",
            "column": "falls",
            "kind": "rate",
            "denominator_column": "patient_days",
        },
        "time_structure": {"has_dates": True, "date_column": "month", "granularity": "month"},
        "status": {
            "primary_outcome.column": "user-confirmed",
            "time_structure.date_column": "user-confirmed",
            "primary_outcome.denominator_column": "inferred",
        },
    }
    base.update(overrides)
    return ProjectDesign.model_validate(base)


def _profile(*cols):
    columns = []
    roles = {"date": [], "outcome": [], "numerator": [], "denominator": [], "grouping": [], "pairing_id": [], "binary": []}
    for name, inferred, role in cols:
        columns.append({"name": name, "inferred_type": inferred})
        if role:
            roles.setdefault(role, []).append(name)
    return {"columns": columns, "candidate_roles": roles, "n_rows": 12}


def test_time_series_rate_proposes_descriptive_u_chart_and_run_chart():
    df = pd.DataFrame({"month": ["2024-01", "2024-02"], "falls": [1, 2], "patient_days": [100, 110]})
    profile = _profile(
        ("month", "Date", "date"),
        ("falls", "Number", "numerator"),
        ("patient_days", "Number", "denominator"),
    )
    items = propose_analyses(_design(), profile, df)
    assert [i.template for i in items] == ["descriptive_summary", "u_c_chart", "run_chart"]
    u = next(i for i in items if i.template == "u_c_chart")
    assert u.parameters["date_col"] == "month"
    assert u.parameters["count_col"] == "falls"
    assert u.parameters["denominator_col"] == "patient_days"
    assert u.param_confidence["count_col"] == "high"
    assert u.param_confidence["denominator_col"] == "medium"


def test_pre_post_continuous_proposes_mean_comparison():
    df = pd.DataFrame({"period": ["pre", "post"], "score": [1.0, 2.0]})
    profile = _profile(("period", "Category", "grouping"), ("score", "Number", "outcome"))
    design = _design(
        comparison="pre-post",
        primary_outcome={"label": "Score", "column": "score", "kind": "continuous"},
        time_structure={"has_dates": False},
        group_column="period",
        pre_label="pre",
        post_label="post",
        status={"primary_outcome.column": "user-confirmed", "group_column": "user-corrected"},
    )
    items = propose_analyses(design, profile, df)
    templates = [i.template for i in items]
    assert "descriptive_summary" in templates
    assert "before_after_mean" in templates
    mean = next(i for i in items if i.template == "before_after_mean")
    assert mean.parameters == {
        "group_col": "period",
        "value_col": "score",
        "pre_val": "pre",
        "post_val": "post",
    }
    assert mean.param_confidence["value_col"] == "high"
    assert mean.param_confidence["group_col"] == "high"


def test_unbound_columns_get_low_confidence():
    df = pd.DataFrame({"month": ["2024-01"], "falls": [1]})
    profile = _profile(("month", "Date", "date"), ("falls", "Number", "numerator"))
    design = _design(
        primary_outcome={"label": "Falls", "column": None, "kind": "count"},
        status={},
    )
    items = propose_analyses(design, profile, df)
    run = next(i for i in items if i.template == "run_chart")
    assert run.parameters.get("value_col") == "falls"
    assert run.param_confidence["value_col"] == "low"
    assert run.needs_clarification is True
