"""Tests for R code generation (all 6 templates)."""
from api.templates.codegen import generate_r_code


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


def test_unknown_template_returns_fallback():
    code = generate_r_code("nonexistent_template", {})
    assert "not yet implemented" in code


def test_generated_code_is_string():
    for t in ["descriptive_summary", "before_after_mean", "before_after_pct",
              "run_chart", "p_chart", "u_c_chart"]:
        code = generate_r_code(t, {})
        assert isinstance(code, str)
        assert len(code) > 10
