import pandas as pd

from api.templates.before_after_mean import run_before_after_mean
from api.templates.before_after_paired import run_before_after_paired
from api.templates.before_after_pct import run_before_after_pct
from api.templates.p_chart import run_p_chart
from api.templates.u_c_chart import run_u_c_chart


def test_before_after_mean_discloses_rows_dropped_for_missing_values():
    df = pd.DataFrame(
        {
            "period": ["pre", "pre", "pre", "post", "post", "post", "during", "during"],
            "value": [1.0, 2.0, None, 3.0, 4.0, None, 5.0, None],
        }
    )

    result = run_before_after_mean(
        df,
        {"group_col": "period", "pre_val": "pre", "post_val": "post", "value_col": "value"},
    )

    assert (
        sum(row["n"] for row in result["table"])
        + result["n_excluded_missing"]
        + result["n_excluded_other_group"]
        == len(df)
    )
    assert result["n_excluded_missing"] == 2
    assert result["n_excluded_other_group"] == 2
    assert "2 records were excluded because value was missing or could not be parsed." in result["methods"]
    assert "2 records were excluded because period did not match either the pre- or post-intervention label." in result["methods"]


def test_before_after_pct_discloses_rows_dropped_for_missing_outcomes():
    df = pd.DataFrame(
        {
            "period": ["pre", "pre", "pre", "post", "post", "post", "during", "during"],
            "outcome": ["yes", "no", None, "yes", "no", None, "yes", None],
        }
    )

    result = run_before_after_pct(
        df,
        {"group_col": "period", "pre_val": "pre", "post_val": "post", "outcome_col": "outcome"},
    )

    assert (
        sum(row["n"] for row in result["table"])
        + result["n_excluded_missing"]
        + result["n_excluded_other_group"]
        == len(df)
    )
    assert result["n_excluded_missing"] == 2
    assert result["n_excluded_other_group"] == 2
    assert "2 records were excluded because values in the binary outcome column were missing." in result["methods"]
    assert "2 records were excluded because period did not match either the pre- or post-intervention label." in result["methods"]


def test_before_after_paired_discloses_unpaired_records():
    df = pd.DataFrame(
        {
            "patient_id": [1, 1, 2, 2, 3],
            "period": ["pre", "post", "pre", "post", "pre"],
            "score": [10.0, 12.0, 20.0, 23.0, 30.0],
        }
    )

    result = run_before_after_paired(
        df,
        {
            "id_col": "patient_id",
            "group_col": "period",
            "value_col": "score",
            "pre_val": "pre",
            "post_val": "post",
        },
    )

    assert result["n_pairs"] * 2 + result["n_dropped_unpaired"] == len(df)
    assert result["n_dropped_unpaired"] == 1
    assert "excluded because they lacked observations in both periods" in result["methods"]


def test_p_chart_discloses_missing_records_and_calendar_gaps():
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-15", "2024-03-01", "2024-03-15"],
            "numerator": [1, 2, 3, None],
            "denominator": [10, 10, 10, 10],
        }
    )

    result = run_p_chart(
        df,
        {
            "date_col": "date",
            "numerator_col": "numerator",
            "denominator_col": "denominator",
            "freq": "MS",
        },
    )

    assert result["n_included_records"] + result["n_excluded_missing"] == result["n_input_records"] == len(df)
    assert len(result["ucl"]) + result["n_excluded_calendar_gaps"] == 3
    assert "1 record was excluded because numerator or denominator values were missing or invalid." in result["methods"]
    assert "1 calendar period was excluded because no uploaded rows were present." in result["methods"]


def test_u_chart_discloses_missing_records_and_calendar_gaps():
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-15", "2024-03-01", "2024-03-15"],
            "count": [1, 2, 3, None],
            "denominator": [10, 10, 10, 10],
        }
    )

    result = run_u_c_chart(
        df,
        {
            "date_col": "date",
            "count_col": "count",
            "denominator_col": "denominator",
            "freq": "MS",
        },
    )

    assert result["n_included_records"] + result["n_excluded_missing"] == result["n_input_records"] == len(df)
    assert len(result["ucl"]) + result["n_excluded_calendar_gaps"] == 3
    assert "1 record was excluded because count or denominator values were missing or invalid." in result["methods"]
    assert "1 calendar period was excluded because no uploaded rows were present." in result["methods"]
