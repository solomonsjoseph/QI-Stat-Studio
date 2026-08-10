"""RED: These tests fail until api/templates/descriptive.py is implemented."""
import pandas as pd
import pytest
from api.templates.descriptive import run_descriptive

FIXTURE = "tests/fixtures/diabetes_care_qi_full.csv"


def test_descriptive_runs_on_sample_csv():
    df = pd.read_csv(FIXTURE)
    result = run_descriptive(df, {"value_cols": ["current_a1c", "age_years"]})
    assert "table" in result
    assert "result_summary" in result
    assert "methods" in result


def test_descriptive_handles_missing_values():
    df = pd.read_csv(FIXTURE)
    # fib4_score is 75% missing — must not crash
    result = run_descriptive(df, {"value_cols": ["fib4_score"]})
    assert "table" in result


def test_descriptive_returns_methods_text():
    df = pd.read_csv(FIXTURE)
    result = run_descriptive(df, {"value_cols": ["current_a1c"]})
    assert len(result["methods"]) > 10


def test_table_rows_carry_ci_keys():
    df = pd.read_csv(FIXTURE)
    result = run_descriptive(df, {"value_cols": ["current_a1c", "age_years"]})
    for row in result["table"]:
        for key in ("mean_ci_low", "mean_ci_high", "median_ci_low", "median_ci_high"):
            assert key in row


def test_small_group_has_mean_ci_but_no_median_ci():
    df = pd.DataFrame({"val": [1, 2, 3, 4]})
    result = run_descriptive(df, {"value_cols": ["val"]})
    row = result["table"][0]
    assert row["median_ci_low"] is None
    assert row["median_ci_high"] is None
    assert row["mean_ci_low"] is not None
    assert row["mean_ci_high"] is not None


def test_single_value_group_has_no_ci_at_all():
    df = pd.DataFrame({"val": [5.0]})
    result = run_descriptive(df, {"value_cols": ["val"]})
    row = result["table"][0]
    assert row["mean_ci_low"] is None
    assert row["mean_ci_high"] is None
    assert row["median_ci_low"] is None
    assert row["median_ci_high"] is None
