"""RED: These tests fail until api/routers/upload.py run_data_quality() is implemented."""
import pandas as pd
import pytest
from api.routers.upload import run_data_quality

FIXTURE = "tests/fixtures/diabetes_care_qi_full.csv"


def load():
    return pd.read_csv(FIXTURE)


def test_detects_period_case_inconsistency():
    df = load()
    flags = run_data_quality(df)
    rules = [f["rule"] for f in flags]
    assert "case_inconsistent" in rules


def test_detects_missing_a1c():
    df = load()
    flags = run_data_quality(df)
    missing_cols = [f["col"] for f in flags if f["rule"] == "missing_pct"]
    # fib4_score is 75% missing by design
    assert any("fib4" in c.lower() for c in missing_cols)


def test_detects_missing_acr():
    df = load()
    flags = run_data_quality(df)
    missing_cols = [f["col"] for f in flags if f["rule"] == "missing_pct"]
    assert len(missing_cols) >= 1


def test_flags_outliers():
    df = load()
    flags = run_data_quality(df)
    rules = [f["rule"] for f in flags]
    # age=219 and egfr=0 are intentional outliers
    assert "outlier_count" in rules


def test_check_time_gaps_zero_on_sample_csv():
    """Sample CSV has 24 consecutive months (2024-2025) — expect 0 gap flags."""
    df = load()
    flags = run_data_quality(df)
    gap_flags = [f for f in flags if f["rule"] == "check_time_gaps"]
    assert len(gap_flags) == 0


def test_check_time_gaps_detects_missing_month():
    """Artificially drop a month to verify the rule triggers."""
    df = load()
    df["_date"] = pd.to_datetime(df["encounter_date"], errors="coerce")
    # Remove all rows from March 2024
    df = df[~((df["_date"].dt.year == 2024) & (df["_date"].dt.month == 3))]
    df = df.drop(columns=["_date"])
    flags = run_data_quality(df)
    gap_flags = [f for f in flags if f["rule"] == "check_time_gaps"]
    assert len(gap_flags) == 1
    assert "1 month" in gap_flags[0]["msg"]


def test_duplicate_id_is_error():
    df = load()
    # Duplicate the first row to force a duplicate encounter_id
    dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    flags = run_data_quality(dup)
    error_flags = [f for f in flags if f["severity"] == "ERROR"]
    assert any(f["rule"] == "duplicate_id" for f in error_flags)


def test_no_duplicate_id_in_sample_csv():
    df = load()
    flags = run_data_quality(df)
    assert not any(f["rule"] == "duplicate_id" for f in flags)


def test_fib4_score_dq_message_includes_expected_behavior_context():
    df = load()
    flags = run_data_quality(df)
    fib4_flags = [f for f in flags if f["col"] == "fib4_score" and f["rule"] == "missing_pct"]
    assert len(fib4_flags) == 1
    assert "often blank when MASLD screening was not done" in fib4_flags[0]["msg"]
    assert "expected behavior" in fib4_flags[0]["msg"]


def test_fib4_score_dq_message_does_not_use_generic_wording():
    df = load()
    flags = run_data_quality(df)
    fib4_flags = [f for f in flags if f["col"] == "fib4_score" and f["rule"] == "missing_pct"]
    assert len(fib4_flags) == 1
    assert "if this is your outcome column" not in fib4_flags[0]["msg"]
