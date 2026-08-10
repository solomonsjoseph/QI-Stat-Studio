"""Tests for run_chart, p_chart, u_c_chart templates (previously untested)."""
import pandas as pd
import numpy as np
import pytest
from api.templates.run_chart import run_run_chart
from api.templates.p_chart import run_p_chart
from api.templates.u_c_chart import run_u_c_chart


# ── shared fixture ──────────────────────────────────────────────────────────

def _monthly_df(n=18):
    """18 months of synthetic encounter data."""
    dates = pd.date_range("2023-01-01", periods=n, freq="ME")
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "encounter_date": dates.strftime("%Y-%m-%d"),
        "hba1c": rng.uniform(6.5, 10.0, n),
        "outcome": rng.integers(0, 2, n),          # binary 0/1
        "count_col": rng.integers(1, 10, n),
        "denom_col": rng.integers(10, 30, n),
    })


# ── run_chart ───────────────────────────────────────────────────────────────

class TestRunChart:
    def test_returns_figure_base64(self):
        df = _monthly_df()
        result = run_run_chart(df, {"date_col": "encounter_date", "value_col": "hba1c"})
        assert result["figure_base64"] is not None
        assert len(result["figure_base64"]) > 100

    def test_returns_median_in_summary(self):
        df = _monthly_df()
        result = run_run_chart(df, {"date_col": "encounter_date", "value_col": "hba1c"})
        assert "Median=" in result["result_summary"]

    def test_returns_methods_text(self):
        df = _monthly_df()
        result = run_run_chart(df, {"date_col": "encounter_date", "value_col": "hba1c"})
        assert "run chart" in result["methods"].lower()
        assert "median" in result["methods"].lower()

    def test_signal_detected_with_long_run(self):
        """8+ consecutive values above median → signal detected."""
        dates = pd.date_range("2023-01-01", periods=16, freq="ME")
        vals = [5.0] * 8 + [10.0] * 8   # first 8 below, next 8 above → run of 8
        df = pd.DataFrame({"encounter_date": dates.strftime("%Y-%m-%d"), "val": vals})
        result = run_run_chart(df, {"date_col": "encounter_date", "value_col": "val"})
        assert result["signal_detected"] is True
        assert result["max_run"] >= 8

    def test_no_signal_with_short_runs(self):
        """Alternating values never form a run ≥8."""
        dates = pd.date_range("2023-01-01", periods=12, freq="ME")
        vals = [5.0, 10.0] * 6   # alternates → max run = 1
        df = pd.DataFrame({"encounter_date": dates.strftime("%Y-%m-%d"), "val": vals})
        result = run_run_chart(df, {"date_col": "encounter_date", "value_col": "val"})
        assert result["signal_detected"] is False

    def test_intervention_date_does_not_crash(self):
        df = _monthly_df()
        result = run_run_chart(df, {
            "date_col": "encounter_date", "value_col": "hba1c",
            "intervention_date": "2024-01-01",
        })
        assert result["figure_base64"] is not None


# ── p_chart ─────────────────────────────────────────────────────────────────

class TestPChart:
    def test_returns_figure_base64(self):
        df = _monthly_df()
        result = run_p_chart(df, {"date_col": "encounter_date", "numerator_col": "outcome"})
        assert result["figure_base64"] is not None

    def test_ucl_above_pbar(self):
        df = _monthly_df()
        result = run_p_chart(df, {"date_col": "encounter_date", "numerator_col": "outcome"})
        assert all(ucl > result["pbar"] for ucl in result["ucl"])

    def test_lcl_non_negative(self):
        df = _monthly_df()
        result = run_p_chart(df, {"date_col": "encounter_date", "numerator_col": "outcome"})
        assert min(result["lcl"]) >= 0.0

    def test_methods_mentions_p_chart(self):
        df = _monthly_df()
        result = run_p_chart(df, {"date_col": "encounter_date", "numerator_col": "outcome"})
        assert "p-chart" in result["methods"].lower()

    def test_with_explicit_denominator(self):
        df = _monthly_df()
        result = run_p_chart(df, {
            "date_col": "encounter_date",
            "numerator_col": "count_col",
            "denominator_col": "denom_col",
        })
        assert result["pbar"] > 0

    def test_varying_denominators_produce_per_point_control_limits(self):
        df = pd.DataFrame({
            "encounter_date": ["2024-01-01", "2024-02-01", "2024-03-01"],
            "events": [1, 4, 9],
            "eligible": [10, 40, 200],
        })
        result = run_p_chart(df, {
            "date_col": "encounter_date",
            "numerator_col": "events",
            "denominator_col": "eligible",
        })

        assert len(result["ucl"]) == 3
        assert max(result["ucl"]) != min(result["ucl"])

    def test_pbar_is_weighted_by_total_numerator_and_denominator(self):
        df = pd.DataFrame({
            "encounter_date": ["2024-01-01", "2024-02-01"],
            "events": [1, 90],
            "eligible": [10, 100],
        })
        result = run_p_chart(df, {
            "date_col": "encounter_date",
            "numerator_col": "events",
            "denominator_col": "eligible",
        })

        assert result["pbar"] == pytest.approx((1 + 90) / (10 + 100), abs=1e-4)
        assert result["pbar"] != pytest.approx(((1 / 10) + (90 / 100)) / 2, abs=1e-4)

    def test_out_of_control_detection_uses_each_period_denominator(self):
        dates = pd.date_range("2020-01-01", periods=101, freq="MS")
        df = pd.DataFrame({
            "encounter_date": dates,
            "events": [2] * 100 + [350],
            "eligible": [10] * 100 + [1000],
        })
        result = run_p_chart(df, {
            "date_col": "encounter_date",
            "numerator_col": "events",
            "denominator_col": "eligible",
        })

        pbar = (100 * 2 + 350) / (100 * 10 + 1000)
        old_nbar = (100 * 10 + 1000) / 101
        old_ucl = pbar + 3 * np.sqrt(pbar * (1 - pbar) / old_nbar)
        target_rate = 350 / 1000

        assert target_rate < old_ucl
        assert target_rate > result["ucl"][-1]
        assert "1 out-of-control point(s)" in result["result_summary"]

    def test_intervention_date_does_not_crash(self):
        df = _monthly_df()
        result = run_p_chart(df, {
            "date_col": "encounter_date", "numerator_col": "outcome",
            "intervention_date": "2024-01-01",
        })
        assert result["figure_base64"] is not None

    def test_calendar_gap_not_charted_as_measured_zero(self):
        """Two real months eleven months apart span 12 monthly buckets on
        resample; only the 2 real ones should appear, not 12 with 10 phantom
        0/0 points."""
        df = pd.DataFrame({
            "encounter_date": ["2024-01-05", "2024-12-10"],
            "events": [3, 5],
            "eligible": [100, 120],
        })
        result = run_p_chart(df, {
            "date_col": "encounter_date", "numerator_col": "events", "denominator_col": "eligible",
        })
        assert len(result["ucl"]) == 2
        assert "2 time points" in result["methods"]

    def test_blank_numerator_row_excluded_not_charted_as_zero(self):
        """A row with a real denominator but a blank numerator must be
        dropped entirely, not summed in as a confirmed zero-event reading."""
        df = pd.DataFrame({
            "encounter_date": ["2024-01-15", "2024-02-15", "2024-03-15"],
            "events": [2, None, 3],
            "eligible": [300, 310, 295],
        })
        result = run_p_chart(df, {
            "date_col": "encounter_date", "numerator_col": "events", "denominator_col": "eligible",
        })
        assert "2 time points" in result["methods"]
        assert result["pbar"] == round((2 + 3) / (300 + 295), 4)


# ── u_c_chart ────────────────────────────────────────────────────────────────

class TestUCChart:
    def test_c_chart_returns_figure(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {"date_col": "encounter_date", "count_col": "count_col"})
        assert result["figure_base64"] is not None

    def test_c_chart_ucl_above_mean(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {"date_col": "encounter_date", "count_col": "count_col"})
        assert min(result["ucl"]) > max(result["lcl"])

    def test_u_chart_with_denominator(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {
            "date_col": "encounter_date",
            "count_col": "count_col",
            "denominator_col": "denom_col",
        })
        assert result["figure_base64"] is not None
        assert max(result["ucl"]) > 0
        assert result["chart_type"] == "u"

    def test_constant_denominator_uses_c_chart(self):
        df = pd.DataFrame({
            "encounter_date": ["2024-01-01", "2024-02-01", "2024-03-01"],
            "events": [3, 4, 5],
            "eligible": [100, 100, 100],
        })
        result = run_u_c_chart(df, {
            "date_col": "encounter_date",
            "count_col": "events",
            "denominator_col": "eligible",
        })

        assert result["chart_type"] == "c"
        assert max(result["ucl"]) == min(result["ucl"])
        assert max(result["lcl"]) == min(result["lcl"])
        assert "denominator is stable across periods" in result["methods"]

    def test_lcl_non_negative(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {"date_col": "encounter_date", "count_col": "count_col"})
        assert min(result["lcl"]) >= 0.0

    def test_methods_mentions_chart_type(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {"date_col": "encounter_date", "count_col": "count_col"})
        assert "chart" in result["methods"].lower()

    def test_intervention_date_does_not_crash(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {
            "date_col": "encounter_date", "count_col": "count_col",
            "intervention_date": "2024-01-01",
        })
        assert result["figure_base64"] is not None

    def test_calendar_gap_not_charted_as_measured_zero(self):
        """Two real months eleven months apart span 12 monthly buckets on
        resample; only the 2 real ones should appear, not 12 with 10 phantom
        0/0 points."""
        df = pd.DataFrame({
            "encounter_date": ["2024-01-05", "2024-12-10"],
            "events": [3, 5],
            "eligible": [100, 120],
        })
        result = run_u_c_chart(df, {
            "date_col": "encounter_date", "count_col": "events", "denominator_col": "eligible",
        })
        assert len(result["ucl"]) == 2
        assert "2 time points" in result["methods"]

    def test_blank_count_row_excluded_not_charted_as_zero(self):
        """A row with a real denominator but a blank count must be dropped
        entirely, not summed in as a confirmed zero-event reading."""
        df = pd.DataFrame({
            "encounter_date": ["2024-01-15", "2024-02-15", "2024-03-15"],
            "events": [2, None, 3],
            "eligible": [300, 310, 295],
        })
        result = run_u_c_chart(df, {
            "date_col": "encounter_date", "count_col": "events", "denominator_col": "eligible",
        })
        assert "2 time points" in result["methods"]
        expected_ubar = (2 + 3) / (300 + 295)
        assert abs(result["ucl"][-1] - (expected_ubar + 3 * (expected_ubar / 295) ** 0.5)) < 1e-4
