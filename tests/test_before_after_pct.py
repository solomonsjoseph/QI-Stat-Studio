"""RED: These tests fail until api/templates/before_after_pct.py is implemented."""
import re
import pandas as pd
import pytest
from api.templates.before_after_pct import run_before_after_pct

FIXTURE = "tests/fixtures/diabetes_care_qi_full.csv"

PARAMS = {
    "group_col": "period",
    "pre_val": "pre",
    "post_val": "post",
    "outcome_col": "a1c_at_goal",
}


def test_before_after_pct_produces_pvalue():
    df = pd.read_csv(FIXTURE)
    result = run_before_after_pct(df, PARAMS)
    assert "p_value" in result
    assert 0.0 <= result["p_value"] <= 1.0


def test_selects_chisq_or_fisher():
    df = pd.read_csv(FIXTURE)
    result = run_before_after_pct(df, PARAMS)
    assert result["test_used"] in ("Chi-square test", "Fisher's exact test")


def test_norm_group_handles_mixed_case():
    """_norm_group must be defined locally in before_after_pct.py — not imported."""
    df = pd.read_csv(FIXTURE).copy()
    df["period"] = df["period"].str.capitalize()  # "Pre", "Post"
    result = run_before_after_pct(df, PARAMS)
    assert "p_value" in result


def test_yes_no_outcome_is_treated_as_binary_percentage():
    df = pd.DataFrame({
        "period": ["pre", "pre", "post", "post"],
        "screened": ["No", "Yes", "Yes", "YES"],
    })
    result = run_before_after_pct(df, {
        "group_col": "period", "pre_val": "pre", "post_val": "post",
        "outcome_col": "screened",
    })
    assert result["table"] == [
        {"group": "pre", "n": 2, "pct": 50.0},
        {"group": "post", "n": 2, "pct": 100.0},
    ]
    assert 0.0 <= result["p_value"] <= 1.0


def test_boolean_and_numeric_string_outcomes_are_binary():
    df = pd.DataFrame({
        "period": ["pre", "pre", "post", "post"],
        "done": [False, "0", True, "1"],
    })
    result = run_before_after_pct(df, {
        "group_col": "period", "pre_val": "pre", "post_val": "post",
        "outcome_col": "done",
    })
    assert [row["pct"] for row in result["table"]] == [0.0, 100.0]


def test_one_sided_binary_levels_add_zero_count_cells():
    df = pd.DataFrame({
        "period": ["pre", "pre", "post", "post"],
        "screened": ["No", "No", "Yes", "Yes"],
    })
    result = run_before_after_pct(df, {
        "group_col": "period", "pre_val": "pre", "post_val": "post",
        "outcome_col": "screened",
    })
    assert result["test_used"] == "Fisher's exact test"
    assert result["table"][0]["pct"] == 0.0
    assert result["table"][1]["pct"] == 100.0


def test_non_binary_outcome_is_rejected_clearly():
    df = pd.DataFrame({
        "period": ["pre"] * 3 + ["post"] * 3,
        "stage": [1, 2, 3, 1, 2, 3],
    })
    with pytest.raises(ValueError, match="must be binary"):
        run_before_after_pct(df, {
            "group_col": "period", "pre_val": "pre", "post_val": "post",
            "outcome_col": "stage",
        })



def test_risk_difference_reports_ci_and_newcombe_method():
    df = pd.DataFrame({
        "period": ["pre"] * 100 + ["post"] * 100,
        "outcome": [1] * 10 + [0] * 90 + [1] * 30 + [0] * 70,
    })
    result = run_before_after_pct(df, {
        "group_col": "period", "pre_val": "pre", "post_val": "post",
        "outcome_col": "outcome",
    })
    assert re.search(
        r"Risk difference \+20\.0 percentage points \(95% CI \d+\.\d to \d+\.\d\)",
        result["result_summary"],
    )
    assert "Newcombe's hybrid score method" in result["methods"]
    assert result["risk_difference_pct_points"] == 20.0


def test_odds_ratio_orientation_matches_fisher_when_chi_square_fires():
    """The chi-square branch must report the same odds-ratio orientation as
    Fisher's exact test: greater than 1 when the outcome is more common
    post than pre. This branch previously reported the reciprocal."""
    df = pd.DataFrame({
        "period": ["pre"] * 100 + ["post"] * 100,
        "outcome": [1] * 20 + [0] * 80 + [1] * 50 + [0] * 50,
    })
    result = run_before_after_pct(df, {
        "group_col": "period", "pre_val": "pre", "post_val": "post",
        "outcome_col": "outcome",
    })
    assert result["test_used"] == "Chi-square test"
    assert result["odds_ratio"] > 1.0


def test_interpretation_uses_signed_difference_matching_ci_direction():
    """When the proportion decreases, the interpretation sentence must report
    a signed (negative) point estimate, not abs(rd*100), so it doesn't sit
    outside its own wholly-negative confidence interval."""
    df = pd.DataFrame({
        "period": ["pre"] * 100 + ["post"] * 100,
        "outcome": [1] * 40 + [0] * 60 + [1] * 25 + [0] * 75,
    })
    result = run_before_after_pct(df, {
        "group_col": "period", "pre_val": "pre", "post_val": "post",
        "outcome_col": "outcome",
    })
    assert result["risk_difference_pct_points"] < 0
    match = re.search(
        r"absolute difference of ([+-]?\d+\.\d) percentage points",
        result["interpretation"],
    )
    assert match is not None
    assert match.group(1).startswith("-"), result["interpretation"]
    assert float(match.group(1)) == result["risk_difference_pct_points"]