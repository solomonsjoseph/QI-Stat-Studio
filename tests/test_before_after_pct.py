"""RED: These tests fail until api/templates/before_after_pct.py is implemented."""
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
