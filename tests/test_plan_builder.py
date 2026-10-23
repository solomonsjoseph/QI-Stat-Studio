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


# --- saved column roles (Data Review role table) -------------------------------------------

import json
from types import SimpleNamespace

from api.dataset_profile import build_profile, get_effective_profile


def _staff_df():
    n = 24
    return pd.DataFrame({
        "month": pd.date_range("2023-01-01", periods=n, freq="MS").astype(str),
        "falls": [(i % 4) + 2 for i in range(n)],
        "staff_score": [60 + (i * 7) % 25 for i in range(n)],  # integer >= falls: guessed denominator
        "patient_days": [1000 + (i * 13) % 60 for i in range(n)],
    })


def _upload(df, roles):
    profile = build_profile(df, {"month": "Date", "falls": "Number", "staff_score": "Number", "patient_days": "Number"})
    profile["candidate_roles"]["denominator"] = ["staff_score", "patient_days"]  # the live-test guess order
    return SimpleNamespace(dataset_profile=json.dumps(profile), column_roles=json.dumps(roles), col_types="{}")


def _rate_design(**kw):
    return _design(primary_outcome={"label": "Falls", "column": "falls", "kind": "rate"},
                   status={"primary_outcome.column": "user-confirmed"}, **kw)


def _uc(items):
    return next(i for i in items if i.template == "u_c_chart")


def test_guess_picks_wrong_denominator_without_saved_roles():
    df = _staff_df()
    up = _upload(df, {})
    assert json.loads(up.dataset_profile)["candidate_roles"]["denominator"][0] == "staff_score"
    items = propose_analyses(_rate_design(), get_effective_profile(up), df)
    assert _uc(items).parameters["denominator_col"] == "staff_score"


def test_saved_role_overrides_guessed_denominator():
    df = _staff_df()
    up = _upload(df, {"patient_days": "denominator", "staff_score": "outcome", "falls": "numerator"})
    profile = get_effective_profile(up)
    assert profile["candidate_roles"]["denominator"][0] == "patient_days"
    assert "staff_score" not in profile["candidate_roles"]["denominator"]
    assert _uc(propose_analyses(_rate_design(), profile, df)).parameters["denominator_col"] == "patient_days"


def test_none_role_is_not_chosen_and_missing_denominator_is_reported():
    df = _staff_df()
    up = _upload(df, {"staff_score": "", "patient_days": ""})
    profile = get_effective_profile(up)
    assert profile["candidate_roles"]["denominator"] == []
    u = _uc(propose_analyses(_rate_design(), profile, df))
    assert "denominator_col" not in u.parameters
    assert u.needs_clarification
    assert "denominator" in u.limitations[0].lower()


def test_unassigned_columns_keep_guesses_and_no_roles_is_unchanged():
    df = _staff_df()
    up = _upload(df, {"falls": "numerator"})
    base = json.loads(up.dataset_profile)["candidate_roles"]
    eff = get_effective_profile(up)["candidate_roles"]
    assert eff["denominator"] == base["denominator"]
    assert get_effective_profile(_upload(df, {})) == json.loads(up.dataset_profile)


def test_design_denominator_beats_saved_role():
    df = _staff_df()
    up = _upload(df, {"staff_score": "denominator"})
    design = _design(primary_outcome={"label": "Falls", "column": "falls", "kind": "rate",
                                      "denominator_column": "patient_days"})
    assert _uc(propose_analyses(design, get_effective_profile(up), df)).parameters["denominator_col"] == "patient_days"


def test_missing_denominator_text_states_consequence():
    df = _staff_df()
    up = _upload(df, {"staff_score": "", "patient_days": ""})
    u = _uc(propose_analyses(_rate_design(), get_effective_profile(up), df))
    assert u.needs_clarification
    assert "Without a denominator this runs as a counts-only C chart, which assumes the same exposure every period." in u.limitations[0]


def test_two_denominators_need_review_and_name_the_used_column():
    df = _staff_df()
    up = _upload(df, {})  # both staff_score and patient_days are denominator candidates
    design = _rate_design()
    design.primary_outcome.denominator_column = None
    u = _uc(propose_analyses(design, get_effective_profile(up), df))
    assert u.parameters["denominator_col"] == "staff_score"
    assert u.needs_clarification
    assert ("Two columns are set as Denominator. This analysis will use staff_score. "
            "Change the other one in the Data Review role table if that is wrong.") in u.limitations


def test_single_denominator_adds_no_conflict_note():
    df = _staff_df()
    up = _upload(df, {"staff_score": "outcome"})
    u = _uc(propose_analyses(_rate_design(), get_effective_profile(up), df))
    assert not any("set as Denominator" in x for x in u.limitations)
