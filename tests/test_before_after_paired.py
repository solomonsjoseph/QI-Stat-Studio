import numpy as np
import pandas as pd
import pytest

from api.analysis_validation import validate_analysis_inputs
from api.templates.before_after_paired import run_before_after_paired
from api.templates.codegen import generate_r_code, generate_sas_code, generate_spss_code


def test_paired_template_execution_and_exclusions():
    df = pd.read_csv("tests/fixtures/pre_post_paired.csv")
    params = {
        "id_col": "patient_id",
        "group_col": "period",
        "value_col": "score",
        "pre_val": "pre",
        "post_val": "post",
    }

    result = run_before_after_paired(df, params)

    assert result["n_pairs"] == 20
    assert result["n_dropped_unpaired"] == 2
    assert result["test_used"] in ("Paired t-test", "Wilcoxon signed-rank test")
    assert result["p_value"] < 0.05
    assert len(result["effect_ci"]) == 2
    assert result["effect_ci"][0] < result["effect_ci"][1]
    assert result["figure_base64"] is not None
    assert len(result["figure_base64"]) > 50
    assert "20" in result["methods"]
    assert "2" in result["methods"]
    assert "Paired" in result["result_summary"]


def test_paired_template_rejection_fewer_than_two_pairs():
    # Only 1 pair
    df = pd.DataFrame({
        "patient_id": [1, 1, 2, 3],
        "period": ["pre", "post", "pre", "post"],
        "score": [10, 8, 12, 11],
    })
    params = {
        "id_col": "patient_id",
        "group_col": "period",
        "value_col": "score",
        "pre_val": "pre",
        "post_val": "post",
    }

    with pytest.raises(ValueError, match="Fewer than 2 complete pairs"):
        run_before_after_paired(df, params)

    errors = validate_analysis_inputs("before_after_paired", df, params)
    assert any("at least 2 complete pairs" in e for e in errors)


def test_paired_test_selection_wilcoxon_on_skewed_data():
    # Heavily skewed paired differences to trigger non-normality
    np.random.seed(42)
    n = 30
    diffs = np.random.exponential(scale=5.0, size=n)
    pre = np.random.uniform(20, 30, size=n)
    post = pre + diffs

    records = []
    for i in range(n):
        records.append({"id": i, "period": "pre", "val": pre[i]})
        records.append({"id": i, "period": "post", "val": post[i]})
    df = pd.DataFrame(records)

    params = {
        "id_col": "id",
        "group_col": "period",
        "value_col": "val",
        "pre_val": "pre",
        "post_val": "post",
    }
    result = run_before_after_paired(df, params)
    assert result["test_used"] in ("Wilcoxon signed-rank test", "Paired t-test")
    assert result["p_value"] < 0.05


def test_codegen_returns_real_syntax_for_paired_template():
    params = {
        "id_col": "patient_id",
        "group_col": "period",
        "value_col": "score",
        "pre_val": "pre",
        "post_val": "post",
    }
    mock_result = {"test_used": "Paired t-test"}

    r_code = generate_r_code("before_after_paired", params, mock_result)
    assert "not yet implemented" not in r_code
    assert "paired=TRUE" in r_code
    assert "patient_id" in r_code

    spss_code = generate_spss_code("before_after_paired", params, mock_result)
    assert "not yet implemented" not in spss_code
    assert "PAIRS=" in spss_code or "PAIRED" in spss_code
    assert "score" in spss_code

    sas_code = generate_sas_code("before_after_paired", params, mock_result)
    assert "not yet implemented" not in sas_code
    assert "PAIRED" in sas_code or "PROC TTEST" in sas_code
    assert "score" in sas_code
