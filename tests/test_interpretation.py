"""RED: Each analysis template must return an 'interpretation' key for the report."""
import sys
sys.path.insert(0, '/projectsp/f_wj183_1/work/Solomon/AI-Assisted-projects/QI_Stat_Studio/qi_stat_studio')

import pandas as pd
import numpy as np
import pytest

FIXTURE = "tests/fixtures/diabetes_care_qi_full.csv"


def make_df(n=20):
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="ME")
    return pd.DataFrame({
        "encounter_date": dates.strftime("%Y-%m-%d"),
        "hba1c": rng.uniform(6.5, 10.0, n),
        "outcome": rng.integers(0, 2, n).astype(float),
        "period": ["pre"] * (n // 2) + ["post"] * (n - n // 2),
    })


def test_descriptive_has_interpretation():
    from api.templates.descriptive import run_descriptive
    result = run_descriptive(make_df(), {"value_cols": ["hba1c"]})
    assert "interpretation" in result and result["interpretation"]


def test_before_after_mean_has_interpretation():
    from api.templates.before_after_mean import run_before_after_mean
    result = run_before_after_mean(make_df(), {"group_col": "period", "value_col": "hba1c", "pre_val": "pre", "post_val": "post"})
    assert "interpretation" in result and result["interpretation"]


def test_before_after_pct_has_interpretation():
    from api.templates.before_after_pct import run_before_after_pct
    result = run_before_after_pct(make_df(), {"group_col": "period", "outcome_col": "outcome", "pre_val": "pre", "post_val": "post"})
    assert "interpretation" in result and result["interpretation"]


def test_run_chart_has_interpretation():
    from api.templates.run_chart import run_run_chart
    result = run_run_chart(make_df(), {"date_col": "encounter_date", "value_col": "hba1c"})
    assert "interpretation" in result and result["interpretation"]


def test_p_chart_has_interpretation():
    from api.templates.p_chart import run_p_chart
    result = run_p_chart(make_df(), {"date_col": "encounter_date", "numerator_col": "outcome"})
    assert "interpretation" in result and result["interpretation"]


def test_u_c_chart_has_interpretation():
    from api.templates.u_c_chart import run_u_c_chart
    result = run_u_c_chart(make_df(), {"date_col": "encounter_date", "count_col": "outcome"})
    assert "interpretation" in result and result["interpretation"]
