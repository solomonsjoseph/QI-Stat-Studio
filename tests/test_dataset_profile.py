import pandas as pd
import pytest

from api.dataset_profile import build_profile, get_upload_profile


def test_profile_role_inference_on_crafted_frame():
    # Frame with date, numerator/denominator pair, grouping, pairing id, outcome, binary
    df = pd.DataFrame({
        "patient_id": [1, 2, 3, 4, 1, 2, 3, 4],  # repeats, so pairing_id candidate
        "encounter_date": pd.date_range("2024-01-01", periods=8, freq="D").strftime("%Y-%m-%d"),
        "infections": [1, 0, 2, 1, 0, 1, 0, 2],  # numerator candidate
        "patient_days": [10, 12, 15, 11, 10, 14, 12, 16],  # denominator candidate
        "unit": ["ICU", "3W", "ICU", "3W", "ICU", "3W", "ICU", "3W"],  # grouping candidate (2 levels)
        "antibiotic_given": ["yes", "no", "yes", "yes", "no", "yes", "no", "yes"],  # binary
        "los": [3.5, 4.2, 7.1, 2.8, 3.0, 5.5, 4.0, 6.2],  # outcome
    })
    col_types = {
        "patient_id": "ID",
        "encounter_date": "Date",
        "infections": "Number",
        "patient_days": "Number",
        "unit": "Category",
        "antibiotic_given": "Yes/No",
        "los": "Number",
    }

    profile = build_profile(df, col_types, dictionary_text="infections: number of catheter-associated infections.\npatient_days: total patient days on unit.")

    assert profile["row_count"] == 8
    assert profile["column_count"] == 7
    roles = profile["candidate_roles"]

    assert "encounter_date" in roles["date"]
    assert "antibiotic_given" in roles["binary"]
    assert "patient_id" in roles["identifier"]
    assert "patient_id" in roles["pairing_id"]
    assert "unit" in roles["grouping"]
    assert "infections" in roles["numerator"]
    assert "patient_days" in roles["denominator"]
    assert "los" in roles["outcome"]

    # Check dictionary definition extraction
    col_map = {c["name"]: c for c in profile["columns"]}
    assert "catheter-associated" in (col_map["infections"]["dictionary_definition"] or "")
    assert "total patient days" in (col_map["patient_days"]["dictionary_definition"] or "")


def test_sample_values_only_for_low_cardinality_categoricals():
    df = pd.DataFrame({
        "id_col": [f"id_{i}" for i in range(10)],
        "date_col": pd.date_range("2024-01-01", periods=10).strftime("%Y-%m-%d"),
        "numeric_col": [float(i) for i in range(10)],
        "text_free": [f"free notes text {i}" for i in range(10)],
        "category_low": ["pre", "post", "pre", "post", "pre", "post", "pre", "post", "pre", "post"],
        "binary_col": ["yes", "no", "yes", "no", "yes", "no", "yes", "no", "yes", "no"],
    })
    col_types = {
        "id_col": "ID",
        "date_col": "Date",
        "numeric_col": "Number",
        "text_free": "Text",
        "category_low": "Category",
        "binary_col": "Yes/No",
    }

    profile = build_profile(df, col_types)
    col_map = {c["name"]: c for c in profile["columns"]}

    # Absent for ID, Date, Number, Text
    assert col_map["id_col"]["sample_values"] == []
    assert col_map["date_col"]["sample_values"] == []
    assert col_map["numeric_col"]["sample_values"] == []
    assert col_map["text_free"]["sample_values"] == []

    # Present for low-cardinality Category and Yes/No
    assert set(col_map["category_low"]["sample_values"]) == {"pre", "post"}
    assert set(col_map["binary_col"]["sample_values"]) == {"yes", "no"}


def test_numeric_summary_and_date_range():
    df = pd.DataFrame({
        "vals": [10.0, 20.0, 30.0, 40.0],
        "dates": ["2023-01-01", "2023-06-01", "2023-12-31", "2023-03-15"],
    })
    col_types = {"vals": "Number", "dates": "Date"}
    profile = build_profile(df, col_types)
    col_map = {c["name"]: c for c in profile["columns"]}

    assert col_map["vals"]["numeric_summary"]["min"] == 10.0
    assert col_map["vals"]["numeric_summary"]["max"] == 40.0
    assert col_map["vals"]["numeric_summary"]["mean"] == 25.0
    assert col_map["dates"]["date_range"]["min"] == "2023-01-01"
    assert col_map["dates"]["date_range"]["max"] == "2023-12-31"
