"""RED: These tests fail until api/routers/analyze.py select_template() is implemented.

Tests cover short-form (substring) answers AND full-option-text answers that
IntakeQuestions.jsx sends — both must work via substring matching.
"""
import pytest
from api.routers.analyze import select_template


# --- Short-form answers (substring matching) ---

def test_descriptive_when_no_comparison_groups():
    assert select_template({"q3": "no", "q4": "groups", "q2": "count", "q6": 5})[0] == "descriptive_summary"


def test_p_chart_for_time_percentage_high_n():
    assert select_template({"q3": "yes", "q4": "time", "q2": "percentage", "q6": 15})[0] == "p_chart"


def test_u_chart_for_time_rate_high_n():
    assert select_template({"q3": "yes", "q4": "time", "q2": "rate", "q6": 14})[0] == "u_c_chart"


def test_run_chart_for_time_low_n():
    assert select_template({"q3": "yes", "q4": "time", "q2": "percentage", "q6": 8})[0] == "run_chart"


def test_before_after_mean_for_average():
    assert select_template({"q3": "yes", "q4": "groups", "q2": "average", "q6": 100})[0] == "before_after_mean"


def test_before_after_pct_for_percentage_groups():
    assert select_template({"q3": "yes", "q4": "groups", "q2": "percentage", "q6": 50})[0] == "before_after_pct"


def test_default_run_chart_for_unsure():
    assert select_template({"q3": "unsure", "q4": "unsure", "q2": "unsure", "q6": 20})[0] == "run_chart"


def test_something_else_defaults_to_run_chart():
    """'Something else' for Q2 should fall through to run_chart default."""
    assert select_template({"q3": "yes", "q4": "time", "q2": "something else", "q6": 20})[0] == "run_chart"


# --- Full-option-text answers (exactly what IntakeQuestions.jsx sends) ---

def test_full_text_descriptive():
    answers = {
        "q3": "No — I'm just describing one time period",
        "q4": "Comparing groups at one point in time",
        "q2": "A count",
        "q6": "5",
    }
    assert select_template(answers)[0] == "descriptive_summary"


def test_full_text_before_after_mean():
    answers = {
        "q3": "Yes — before and after an intervention",
        "q4": "Comparing groups at one point in time",
        "q2": "An average or median value",
        "q6": "100",
    }
    assert select_template(answers)[0] == "before_after_mean"


def test_full_text_p_chart():
    answers = {
        "q3": "Yes — before and after an intervention",
        "q4": "Tracking over time",
        "q2": "A percentage or proportion",
        "q6": "15",
    }
    assert select_template(answers)[0] == "p_chart"
