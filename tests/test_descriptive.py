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
