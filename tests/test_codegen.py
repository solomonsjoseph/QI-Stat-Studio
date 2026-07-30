"""Tests for R code generation (all 6 templates)."""
from api.templates.codegen import generate_r_code, generate_sas_code, generate_spss_code


def test_descriptive_contains_summarise():
    code = generate_r_code("descriptive_summary", {"value_cols": ["hba1c", "sbp"], "group_col": "site"})
    assert "summarise" in code
    assert "hba1c" in code
    assert "site" in code


def test_before_after_mean_contains_wilcox():
    code = generate_r_code("before_after_mean", {"group_col": "period", "value_col": "hba1c", "pre_val": "pre", "post_val": "post"})
    assert "wilcox.test" in code
    assert "pre" in code
    assert "post" in code


def test_before_after_pct_contains_chisq():
    code = generate_r_code("before_after_pct", {"group_col": "period", "outcome_col": "outcome", "pre_val": "pre", "post_val": "post"})
    assert "chisq.test" in code
    assert "fisher.test" in code


def test_run_chart_contains_ggplot():
    code = generate_r_code("run_chart", {"date_col": "encounter_date", "value_col": "hba1c"})
    assert "ggplot" in code
    assert "median" in code


def test_p_chart_contains_ucl_lcl():
    code = generate_r_code("p_chart", {"date_col": "encounter_date", "numerator_col": "outcome"})
    assert "ucl" in code
    assert "lcl" in code


def test_u_c_chart_contains_cbar():
    code = generate_r_code("u_c_chart", {"date_col": "encounter_date", "count_col": "count"})
    assert "cbar" in code
    assert "ucl" in code


def test_r_before_after_mean_uses_runtime_test_decision():
    code = generate_r_code(
        "before_after_mean",
        {"group_col": "period", "value_col": "hba1c", "pre_val": "pre", "post_val": "post"},
        {"test_used": "Two-sample t-test"},
    )
    assert "Runtime decision: Two-sample t-test" in code
    assert "t.test(pre, post)" in code


def test_r_before_after_pct_uses_runtime_test_decision():
    code = generate_r_code(
        "before_after_pct",
        {"group_col": "period", "outcome_col": "outcome", "pre_val": "pre", "post_val": "post"},
        {"test_used": "Fisher's exact test"},
    )
    assert "Runtime decision: Fisher's exact test" in code
    assert "fisher.test(ct)" in code


def test_p_chart_denominator_code_paths():
    with_denom = generate_r_code("p_chart", {"date_col": "date", "numerator_col": "num", "denominator_col": "denom"})
    without_denom = generate_r_code("p_chart", {"date_col": "date", "numerator_col": "num"})
    assert "denom=sum(denom" in with_denom
    assert "denom=n()" in without_denom


def test_u_c_chart_denominator_selects_u_chart_otherwise_c_chart():
    with_denom = generate_r_code("u_c_chart", {"date_col": "date", "count_col": "cnt", "denominator_col": "denom"})
    without_denom = generate_r_code("u_c_chart", {"date_col": "date", "count_col": "cnt"})
    assert "rate <- agg$cnt / agg$denom" in with_denom
    assert "cbar <- mean(agg$cnt" in without_denom


def test_run_chart_r_mirrors_runtime_aggregation_and_signal_rule():
    code = generate_r_code("run_chart", {"date_col": "date", "value_col": "value"})
    assert "group_by(bucket=format(date" in code
    assert "median(agg$val" in code
    assert "median(df$" not in code
    assert ">= 8" in code
    assert ">=6" not in code


def test_p_chart_r_uses_requested_frequency_bucket():
    code = generate_r_code("p_chart", {"date_col": "date", "numerator_col": "num", "freq": "W"})
    assert "%Y-%U" in code
    assert "'%Y-%m'" not in code


def test_time_series_r_outputs_plot_and_intervention_line():
    params_by_template = {
        "run_chart": {"date_col": "date", "value_col": "value", "intervention_date": "2025-01-01"},
        "p_chart": {"date_col": "date", "numerator_col": "num", "intervention_date": "2025-01-01"},
        "u_c_chart": {"date_col": "date", "count_col": "cnt", "intervention_date": "2025-01-01"},
    }
    for template, params in params_by_template.items():
        code = generate_r_code(template, params)
        assert "ggplot(agg" in code
        assert "geom_vline" in code
        assert "2025-01-01" in code
        assert "bucket_start=min(" in code
        assert "aes(x=bucket_start" in code


def test_u_c_chart_r_uses_runtime_c_chart_decision_with_denominator():
    code = generate_r_code(
        "u_c_chart",
        {"date_col": "date", "count_col": "cnt", "denominator_col": "denom"},
        {"chart_type": "c"},
    )
    assert "cbar <- mean(agg$cnt" in code
    assert "rate <- agg$cnt / agg$denom" not in code


def test_spss_sas_u_c_chart_use_runtime_c_chart_decision_with_denominator():
    params = {"date_col": "date", "count_col": "cnt", "denominator_col": "denom"}
    result = {"chart_type": "c"}
    spss = generate_spss_code("u_c_chart", params, result)
    sas = generate_sas_code("u_c_chart", params, result)
    assert "COMPUTE cbar=MEAN(cnt)" in spss
    assert "COMPUTE rate=cnt/denom" not in spss
    assert "cbar=mean(cnt)" in sas
    assert "rate=cnt/denom" not in sas


def test_unknown_template_returns_fallback():
    code = generate_r_code("nonexistent_template", {})
    assert "not yet implemented" in code


def test_generated_code_is_string():
    for t in ["descriptive_summary", "before_after_mean", "before_after_pct",
              "run_chart", "p_chart", "u_c_chart"]:
        code = generate_r_code(t, {})
        assert isinstance(code, str)
        assert len(code) > 10


# ── SPSS and SAS tests ────────────────────────────────────────────────────



def test_spss_not_placeholder():
    for t in ["descriptive_summary", "before_after_mean", "before_after_pct",
              "run_chart", "p_chart", "u_c_chart"]:
        code = generate_spss_code(t, {})
        assert "Phase 3" not in code, f"{t}: still placeholder"
        assert len(code) > 30


def test_sas_not_placeholder():
    for t in ["descriptive_summary", "before_after_mean", "before_after_pct",
              "run_chart", "p_chart", "u_c_chart"]:
        code = generate_sas_code(t, {})
        assert "Phase 3" not in code, f"{t}: still placeholder"
        assert len(code) > 30


def test_spss_descriptive_contains_frequencies():
    code = generate_spss_code("descriptive_summary", {"value_cols": ["hba1c"], "group_col": "period"})
    assert "DESCRIPTIVES" in code or "FREQUENCIES" in code or "MEANS" in code


def test_spss_before_after_mean_contains_ttest():
    code = generate_spss_code("before_after_mean", {"group_col": "period", "value_col": "hba1c"})
    assert "T-TEST" in code



def test_spss_before_after_mean_uses_wilcoxon_runtime_decision():
    code = generate_spss_code(
        "before_after_mean",
        {"group_col": "period", "value_col": "hba1c"},
        {"test_used": "Wilcoxon rank-sum test"},
    )
    assert "Wilcoxon rank-sum test" in code
    assert "NPAR TESTS" in code
    assert "T-TEST" not in code

def test_spss_before_after_pct_contains_crosstabs():
    code = generate_spss_code("before_after_pct", {"group_col": "period", "outcome_col": "outcome"})
    assert "CROSSTABS" in code


def test_sas_descriptive_contains_proc_means():
    code = generate_sas_code("descriptive_summary", {"value_cols": ["hba1c"], "group_col": "period"})
    assert "PROC MEANS" in code


def test_sas_before_after_mean_contains_proc_ttest():
    code = generate_sas_code("before_after_mean", {"group_col": "period", "value_col": "hba1c"})
    assert "PROC TTEST" in code


def test_sas_before_after_pct_contains_proc_freq():
    code = generate_sas_code("before_after_pct", {"group_col": "period", "outcome_col": "outcome"})
    assert "PROC FREQ" in code



def test_spss_p_and_u_charts_derive_date_bucket_from_params_date_col():
    p_code = generate_spss_code(
        "p_chart",
        {"date_col": "encounter_date", "numerator_col": "outcome", "freq": "MS"},
    )
    u_code = generate_spss_code(
        "u_c_chart",
        {"date_col": "event_date", "count_col": "falls", "denominator_col": "patient_days", "freq": "W"},
    )
    assert "COMPUTE date_bucket=XDATE.MONTH(encounter_date)" in p_code
    assert "COMPUTE date_bucket=XDATE.WEEK(event_date)" in u_code
    assert "/BREAK=date_bucket" in p_code
    assert "/BREAK=date_bucket" in u_code


def test_sas_p_and_u_charts_derive_date_bucket_from_params_date_col():
    p_code = generate_sas_code(
        "p_chart",
        {"date_col": "encounter_date", "numerator_col": "outcome", "freq": "MS"},
    )
    u_code = generate_sas_code(
        "u_c_chart",
        {"date_col": "event_date", "count_col": "falls", "denominator_col": "patient_days", "freq": "W"},
    )
    assert "intnx('month', encounter_date" in p_code
    assert "intnx('week', event_date" in u_code
    assert "GROUP BY date_bucket" in p_code
    assert "GROUP BY date_bucket" in u_code


def test_spss_sas_time_series_include_intervention_comment():
    params = {"date_col": "date", "count_col": "cnt", "intervention_date": "2025-01-01"}
    assert "* Intervention began 2025-01-01; mark it on the chart." in generate_spss_code("u_c_chart", params)
    assert "/* Intervention began 2025-01-01 */" in generate_sas_code("u_c_chart", params)