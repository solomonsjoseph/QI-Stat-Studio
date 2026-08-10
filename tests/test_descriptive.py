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


def test_group_labels_preserve_original_casing():
    """Grouping normalizes case internally to merge 'ICU'/'icu' typos, but the
    displayed label must show the resident's actual data, not the lowercased
    grouping key."""
    df = pd.DataFrame({
        "unit": ["ICU", "ICU", "ICU", "Ward", "Ward", "Ward"],
        "los": [5, 6, 7, 2, 3, 4],
    })
    result = run_descriptive(df, {"group_col": "unit", "value_cols": ["los"]})
    groups = {row["group"] for row in result["table"]}
    assert groups == {"ICU", "Ward"}

def test_string_dtype_numeric_column_does_not_crash():
    """A value_col is not guaranteed to already be numeric dtype (e.g. a
    zero-padded numeric measure preserved as text on upload so a real
    identifier column elsewhere in the file keeps its leading zeros).
    .mean()/.std() on a raw string Series must not raise."""
    df = pd.DataFrame({"score": ["01", "02", "03"]}, dtype=object)
    result = run_descriptive(df, {"value_cols": ["score"]})
    row = result["table"][0]
    assert row["n"] == 3
    assert row["mean"] == 2.0


def test_string_dtype_numeric_column_with_group_does_not_crash():
    df = pd.DataFrame({
        "unit": ["ICU", "ICU", "Ward", "Ward"],
        "score": ["01", "02", "03", "04"],
    })
    result = run_descriptive(df, {"group_col": "unit", "value_cols": ["score"]})
    means = {row["group"]: row["mean"] for row in result["table"]}
    assert means == {"ICU": 1.5, "Ward": 3.5}
