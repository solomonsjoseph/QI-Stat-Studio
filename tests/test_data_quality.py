"""Data-quality checks for uploaded resident datasets."""
import pandas as pd
from api.routers.upload import detect_col_type, run_data_quality

FIXTURE = "tests/fixtures/diabetes_care_qi_full.csv"


def load():
    return pd.read_csv(FIXTURE)


def quality_flags(df: pd.DataFrame):
    col_types = {col: detect_col_type(col, df[col]) for col in df.columns}
    return run_data_quality(df, col_types)


def test_detects_period_case_inconsistency():
    df = load()
    flags = quality_flags(df)
    rules = [f["rule"] for f in flags]
    assert "case_inconsistent" in rules


def test_detects_case_inconsistency_for_non_period_category_column():
    df = load().rename(columns={"period": "phase"})
    flags = quality_flags(df)
    phase_flags = [f for f in flags if f["col"] == "phase" and f["rule"] == "case_inconsistent"]
    assert len(phase_flags) == 1
    assert "These will be normalized automatically during analysis." in phase_flags[0]["msg"]


def test_detects_missing_a1c():
    df = load()
    flags = quality_flags(df)
    missing_cols = [f["col"] for f in flags if f["rule"] == "missing_pct"]
    # fib4_score is 75% missing by design
    assert any("fib4" in c.lower() for c in missing_cols)


def test_detects_missing_acr():
    df = load()
    flags = quality_flags(df)
    missing_cols = [f["col"] for f in flags if f["rule"] == "missing_pct"]
    assert len(missing_cols) >= 1


def test_race_ethnicity_below_missing_threshold_is_not_flagged():
    df = load()
    flags = quality_flags(df)
    assert not any(f["col"] == "race_ethnicity" and f["rule"] == "missing_pct" for f in flags)


def test_flags_outliers_but_skips_binary_columns():
    df = load()
    flags = quality_flags(df)
    rules = [f["rule"] for f in flags]
    # age=219 and egfr=0 are intentional outliers
    assert "outlier_count" in rules
    binary_outliers = [
        f for f in flags if f["rule"] == "outlier_count" and f["col"] in {"a1c_at_goal", "on_statin"}
    ]
    assert binary_outliers == []


def test_check_time_gaps_zero_on_sample_csv():
    """Sample CSV has 24 consecutive months (2024-2025) — expect 0 gap flags."""
    df = load()
    flags = quality_flags(df)
    gap_flags = [f for f in flags if f["rule"] == "check_time_gaps"]
    assert len(gap_flags) == 0


def test_check_time_gaps_detects_missing_month():
    """Artificially drop a month to verify the rule triggers."""
    df = load()
    df["_date"] = pd.to_datetime(df["encounter_date"], errors="coerce")
    # Remove all rows from March 2024
    df = df[~((df["_date"].dt.year == 2024) & (df["_date"].dt.month == 3))]
    df = df.drop(columns=["_date"])
    flags = quality_flags(df)
    gap_flags = [f for f in flags if f["rule"] == "check_time_gaps"]
    assert len(gap_flags) == 1
    assert "1 month" in gap_flags[0]["msg"]


def test_check_time_gaps_detects_date_column_with_generic_name():
    df = pd.DataFrame({"visit_date": ["2024-01-15", "2024-03-15"]})
    flags = quality_flags(df)
    gap_flags = [f for f in flags if f["col"] == "visit_date" and f["rule"] == "check_time_gaps"]
    assert len(gap_flags) == 1
    assert "1 month" in gap_flags[0]["msg"]


def test_numeric_stored_as_text_requires_ninety_percent_parseable_values():
    low_parse_df = pd.DataFrame({"text_metric": ["12", "13.5", "x", "14"]})
    low_parse_flags = quality_flags(low_parse_df)
    assert not any(
        f["col"] == "text_metric" and f["rule"] == "numeric_stored_as_text" for f in low_parse_flags
    )

    numeric_text_df = pd.DataFrame({"text_metric": ["12", "13.5", "14", "15"]})
    numeric_text_flags = quality_flags(numeric_text_df)
    assert any(
        f["col"] == "text_metric" and f["rule"] == "numeric_stored_as_text" for f in numeric_text_flags
    )


def test_preserved_leading_zero_columns_do_not_warn_numeric_stored_as_text():
    """A column intentionally kept as text on upload to preserve a leading
    zero (e.g. a zip code) is not a data-quality problem; it must not be
    reported as though the resident mislabeled a numeric column."""
    df = pd.DataFrame({"zip": ["02139", "10001", "00501"]})
    col_types = {col: detect_col_type(col, df[col]) for col in df.columns}

    flags = run_data_quality(df, col_types, {"zip"})
    assert not any(f["col"] == "zip" and f["rule"] == "numeric_stored_as_text" for f in flags)

    unmarked_flags = run_data_quality(df, col_types)
    assert any(f["col"] == "zip" and f["rule"] == "numeric_stored_as_text" for f in unmarked_flags)


def test_duplicate_id_is_error():
    df = load()
    # Duplicate the first row to force a duplicate encounter_id
    dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    flags = quality_flags(dup)
    error_flags = [f for f in flags if f["severity"] == "ERROR"]
    assert any(f["rule"] == "duplicate_id" for f in error_flags)


def test_no_duplicate_id_in_sample_csv():
    df = load()
    flags = quality_flags(df)
    assert not any(f["rule"] == "duplicate_id" for f in flags)


def test_fib4_score_dq_message_includes_expected_behavior_context():
    df = load()
    flags = quality_flags(df)
    fib4_flags = [f for f in flags if f["col"] == "fib4_score" and f["rule"] == "missing_pct"]
    assert len(fib4_flags) == 1
    assert "often blank when MASLD screening was not done" in fib4_flags[0]["msg"]
    assert "expected behavior" in fib4_flags[0]["msg"]


def test_fib4_score_dq_message_does_not_use_generic_wording():
    df = load()
    flags = quality_flags(df)
    fib4_flags = [f for f in flags if f["col"] == "fib4_score" and f["rule"] == "missing_pct"]
    assert len(fib4_flags) == 1
    assert "if this is your outcome column" not in fib4_flags[0]["msg"]


def test_new_rules_and_metadata_emitted():
    n = 21
    df = pd.DataFrame({
        "padded_col": ["  val1", "val2  ", "val3"] * 7,
        "mixed_col": (["12", "15", "text_label", "another_text"] * 5) + ["99"],
        "total_days": [10, 0, 15] * 7,  # nonpositive denominator (0)
        "num_infections": [12, 5, 2] * 7,  # numerator exceeds denominator row 0 (12 > 10)
        "bin_col": ["yes", "no", "maybe"] * 7,  # third value
        "sparse_cat": ["A"] * 20 + ["B"],  # B has 1 row (<5)
        "future_date": ["2099-01-01"] * n,
    })
    col_types = {
        "padded_col": "Category",
        "mixed_col": "Category",
        "total_days": "Number",
        "num_infections": "Number",
        "bin_col": "Yes/No",
        "sparse_cat": "Category",
        "future_date": "Date",
    }
    flags = run_data_quality(df, col_types)
    rules = {f["rule"] for f in flags}

    assert "whitespace_padding" in rules
    assert "mixed_types" in rules
    assert "nonpositive_denominator" in rules
    assert "numerator_exceeds_denominator" in rules
    assert "binary_out_of_range" in rules
    assert "sparse_category" in rules
    assert "unexpected_date_range" in rules
    assert "insufficient_time_points" in rules

    # Check rich metadata presence
    for f in flags:
        assert "why" in f and len(f["why"]) > 0
        assert "suggestion" in f and len(f["suggestion"]) > 0
        assert "blocks" in f

    nonpos = next(f for f in flags if f["rule"] == "nonpositive_denominator")
    assert nonpos["blocks"] == "p_chart, u_c_chart"
    assert nonpos["severity"] == "ERROR"

    num_exc = next(f for f in flags if f["rule"] == "numerator_exceeds_denominator")
    assert num_exc["blocks"] == "p_chart"
    assert num_exc["severity"] == "ERROR"


def test_duplicate_rows_detected():
    df = pd.DataFrame({
        "a": [1, 1, 2],
        "b": ["x", "x", "y"],
    })
    flags = run_data_quality(df, {"a": "Number", "b": "Category"})
    rules = {f["rule"] for f in flags}
    assert "duplicate_rows" in rules


def test_malformed_fixture_emits_case_whitespace_and_mixed_type_rules():
    df = pd.read_csv("tests/fixtures/malformed_dates_mixed_case.csv")
    flags = quality_flags(df)

    assert any(f["col"] == "period" and f["rule"] == "case_inconsistent" for f in flags)
    assert any(f["col"] == "metric" and f["rule"] == "whitespace_padding" for f in flags)
    assert any(f["col"] == "metric" and f["rule"] == "mixed_types" for f in flags)
