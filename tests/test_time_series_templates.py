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
        assert result["ucl"] > result["pbar"]

    def test_lcl_non_negative(self):
        df = _monthly_df()
        result = run_p_chart(df, {"date_col": "encounter_date", "numerator_col": "outcome"})
        assert result["lcl"] >= 0.0

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

    def test_intervention_date_does_not_crash(self):
        df = _monthly_df()
        result = run_p_chart(df, {
            "date_col": "encounter_date", "numerator_col": "outcome",
            "intervention_date": "2024-01-01",
        })
        assert result["figure_base64"] is not None


# ── u_c_chart ────────────────────────────────────────────────────────────────

class TestUCChart:
    def test_c_chart_returns_figure(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {"date_col": "encounter_date", "count_col": "count_col"})
        assert result["figure_base64"] is not None

    def test_c_chart_ucl_above_mean(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {"date_col": "encounter_date", "count_col": "count_col"})
        assert result["ucl"] > result["lcl"]

    def test_u_chart_with_denominator(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {
            "date_col": "encounter_date",
            "count_col": "count_col",
            "denominator_col": "denom_col",
        })
        assert result["figure_base64"] is not None
        assert result["ucl"] > 0

    def test_lcl_non_negative(self):
        df = _monthly_df()
        result = run_u_c_chart(df, {"date_col": "encounter_date", "count_col": "count_col"})
        assert result["lcl"] >= 0.0

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
