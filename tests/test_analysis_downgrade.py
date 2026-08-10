"""Unit tests for the p_chart/u_c_chart -> run_chart downgrade and the
codegen that has to rebuild a run chart from the raw uploaded columns
after a downgrade swaps template/params.
"""
import pandas as pd

from api.analysis_downgrade import maybe_downgrade_control_chart
from api.templates.codegen import generate_r_code, generate_sas_code, generate_spss_code


def _p_chart_df():
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="MS"),
            "outcome": [1, 0, 1, 0, 1, 0],
            "encounters": [10, 12, 9, 11, 8, 13],
        }
    )


def _u_c_chart_df(with_denominator=True):
    data = {
        "date": pd.date_range("2024-01-01", periods=6, freq="MS"),
        "falls": [1, 2, 0, 3, 1, 2],
    }
    if with_denominator:
        data["patient_days"] = [100, 110, 95, 105, 90, 115]
    return pd.DataFrame(data)


def test_p_chart_downgrade_uses_underscore_value_col_and_source_columns():
    df = _p_chart_df()
    params = {"date_col": "date", "numerator_col": "outcome", "denominator_col": "encounters", "freq": "MS"}

    template, new_df, new_params, count = maybe_downgrade_control_chart("p_chart", df, params)

    assert template == "run_chart"
    assert count == 6
    assert new_params["value_col"] == "outcome_proportion"
    assert " " not in new_params["value_col"]
    assert new_params["source_numerator_col"] == "outcome"
    assert new_params["source_denominator_col"] == "encounters"
    assert new_params["value_col"] in new_df.columns


def test_u_c_chart_downgrade_uses_underscore_rate_col_and_source_columns():
    df = _u_c_chart_df()
    params = {"date_col": "date", "count_col": "falls", "denominator_col": "patient_days", "freq": "MS"}

    template, new_df, new_params, count = maybe_downgrade_control_chart("u_c_chart", df, params)

    assert template == "run_chart"
    assert new_params["value_col"] == "falls_rate"
    assert " " not in new_params["value_col"]
    assert new_params["source_count_col"] == "falls"
    assert new_params["source_denominator_col"] == "patient_days"


def test_u_c_chart_downgrade_without_denominator_omits_source_denominator_col():
    df = _u_c_chart_df(with_denominator=False)
    params = {"date_col": "date", "count_col": "falls", "freq": "MS"}

    template, new_df, new_params, count = maybe_downgrade_control_chart("u_c_chart", df, params)

    assert template == "run_chart"
    assert new_params["value_col"] == "falls"
    assert new_params["source_count_col"] == "falls"
    assert "source_denominator_col" not in new_params


def test_downgraded_p_chart_r_codegen_rebuilds_from_raw_columns():
    df = _p_chart_df()
    params = {"date_col": "date", "numerator_col": "outcome", "denominator_col": "encounters", "freq": "MS"}
    _, _, new_params, _ = maybe_downgrade_control_chart("p_chart", df, params)

    code = generate_r_code("run_chart", new_params)

    assert "outcome" in code
    assert "encounters" in code
    assert "outcome_proportion" not in code
    assert "outcome proportion" not in code
    assert "median(agg$val" in code


def test_downgraded_p_chart_spss_codegen_rebuilds_from_raw_columns():
    df = _p_chart_df()
    params = {"date_col": "date", "numerator_col": "outcome", "denominator_col": "encounters", "freq": "MS"}
    _, _, new_params, _ = maybe_downgrade_control_chart("p_chart", df, params)

    code = generate_spss_code("run_chart", new_params)

    assert "SUM(outcome)" in code
    assert "SUM(encounters)" in code
    assert "outcome_proportion" not in code
    assert "outcome proportion" not in code


def test_downgraded_p_chart_sas_codegen_rebuilds_from_raw_columns():
    df = _p_chart_df()
    params = {"date_col": "date", "numerator_col": "outcome", "denominator_col": "encounters", "freq": "MS"}
    _, _, new_params, _ = maybe_downgrade_control_chart("p_chart", df, params)

    code = generate_sas_code("run_chart", new_params)

    assert "sum(outcome)" in code
    assert "sum(encounters)" in code
    assert "outcome_proportion" not in code
    assert "outcome proportion" not in code


def test_downgraded_u_c_chart_without_denominator_r_codegen_uses_bare_count():
    df = _u_c_chart_df(with_denominator=False)
    params = {"date_col": "date", "count_col": "falls", "freq": "MS"}
    _, _, new_params, _ = maybe_downgrade_control_chart("u_c_chart", df, params)

    code = generate_r_code("run_chart", new_params)

    assert "sum(falls, na.rm=TRUE)" in code
    assert "agg$val <- agg$num" in code
    assert "falls_rate" not in code


def test_non_downgraded_run_chart_codegen_is_unaffected():
    params = {"date_col": "encounter_date", "value_col": "hba1c"}

    r_code = generate_r_code("run_chart", params)
    spss_code = generate_spss_code("run_chart", params)
    sas_code = generate_sas_code("run_chart", params)

    assert "mean(hba1c, na.rm=TRUE)" in r_code
    assert "GRAPH /LINE(SIMPLE)=VALUE(hba1c) BY encounter_date." in spss_code
    assert "SERIES X=encounter_date Y=hba1c;" in sas_code



def test_downgraded_p_chart_without_denominator_r_codegen_divides_by_row_count():
    df = _p_chart_df()
    params = {"date_col": "date", "numerator_col": "outcome", "freq": "MS"}
    _, _, new_params, _ = maybe_downgrade_control_chart("p_chart", df, params)

    code = generate_r_code("run_chart", new_params)

    assert "source_denominator_col" not in new_params
    assert "denom=n()" in code
    assert "agg$val <- agg$num / agg$denom" in code
    assert "outcome_proportion" not in code


def test_downgraded_p_chart_without_denominator_spss_codegen_divides_by_row_count():
    df = _p_chart_df()
    params = {"date_col": "date", "numerator_col": "outcome", "freq": "MS"}
    _, _, new_params, _ = maybe_downgrade_control_chart("p_chart", df, params)

    code = generate_spss_code("run_chart", new_params)

    assert "/denom=N." in code
    assert "COMPUTE val=num/denom." in code


def test_downgraded_p_chart_without_denominator_sas_codegen_divides_by_row_count():
    df = _p_chart_df()
    params = {"date_col": "date", "numerator_col": "outcome", "freq": "MS"}
    _, _, new_params, _ = maybe_downgrade_control_chart("p_chart", df, params)

    code = generate_sas_code("run_chart", new_params)

    assert "count(*) AS denom" in code
    assert "val=num/denom;" in code