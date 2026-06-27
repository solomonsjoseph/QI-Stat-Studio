"""RED: These tests fail until detect_col_type() in api/routers/upload.py is implemented."""
import pandas as pd
import pytest

# Import the internal function via the module that defines it
from api.routers.upload import detect_col_type


def test_detects_id_column():
    s = pd.Series(["E001", "E002", "E003"])
    assert detect_col_type("patient_id", s) == "ID"


def test_detects_encounter_id():
    s = pd.Series([1, 2, 3])
    assert detect_col_type("encounter_id", s) == "ID"


def test_detects_yes_no_binary_numeric():
    s = pd.Series([0, 1, 1, 0, 1])
    assert detect_col_type("a1c_at_goal", s) == "Yes/No"


def test_detects_yes_no_string_values():
    s = pd.Series(["yes", "no", "yes"])
    assert detect_col_type("diabetes_status", s) == "Yes/No"


def test_detects_number():
    s = pd.Series([8.1, 7.4, 9.2, 6.5])
    assert detect_col_type("current_a1c", s) == "Number"


def test_detects_category():
    s = pd.Series(["pre", "post", "pre", "post"])
    assert detect_col_type("period", s) == "Category"


def test_detects_date():
    s = pd.to_datetime(pd.Series(["2024-01-15", "2024-02-20"]))
    assert detect_col_type("encounter_date", s) == "Date"


def test_sample_csv_patient_id_is_id():
    """Integration check: actual CSV column names produce correct types."""
    df = pd.read_csv("tests/fixtures/diabetes_care_qi_full.csv")
    assert detect_col_type("encounter_id", df["encounter_id"]) == "ID"
