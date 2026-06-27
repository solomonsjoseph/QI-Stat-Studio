"""RED: These tests fail until api/templates/before_after_mean.py is implemented."""
import pandas as pd
import pytest
from api.templates.before_after_mean import run_before_after_mean

FIXTURE = "tests/fixtures/diabetes_care_qi_full.csv"

PARAMS = {
    "group_col": "period",
    "pre_val": "pre",
    "post_val": "post",
    "value_col": "current_a1c",
    "intervention_label": "Protocol change",
}


def test_before_after_mean_produces_pvalue():
    df = pd.read_csv(FIXTURE)
    result = run_before_after_mean(df, PARAMS)
    assert "p_value" in result
    assert 0.0 <= result["p_value"] <= 1.0


def test_selects_wilcoxon_or_ttest():
    df = pd.read_csv(FIXTURE)
    result = run_before_after_mean(df, PARAMS)
    assert result["test_used"] in ("Wilcoxon rank-sum test", "Two-sample t-test")


def test_returns_figure():
    df = pd.read_csv(FIXTURE)
    result = run_before_after_mean(df, PARAMS)
    assert "figure_base64" in result
    assert len(result["figure_base64"]) > 100


def test_case_insensitive_group_matching():
    """_norm_group must handle mixed-case period values."""
    df = pd.read_csv(FIXTURE).copy()
    df["period"] = df["period"].str.capitalize()  # "Pre", "Post"
    result = run_before_after_mean(df, PARAMS)
    assert "p_value" in result


def test_returns_table_with_pre_post():
    df = pd.read_csv(FIXTURE)
    result = run_before_after_mean(df, PARAMS)
    groups = [row["group"] for row in result["table"]]
    assert "pre" in groups
    assert "post" in groups
