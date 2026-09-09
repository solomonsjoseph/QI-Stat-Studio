from __future__ import annotations

import base64
import io
from typing import Any, Dict, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


def _norm_group(df: pd.DataFrame, col: str, val: str) -> Tuple[pd.DataFrame, str]:
    if df[col].dtype == object:
        df = df.copy()
        df[col] = df[col].str.strip().str.lower()
        val = val.strip().lower()
    return df, val


def run_before_after_paired(df: pd.DataFrame, params: dict[str, Any]) -> Dict[str, Any]:
    """Run a paired comparison (Paired t-test or Wilcoxon signed-rank test) on repeated observations."""
    id_col = params["id_col"]
    group_col = params["group_col"]
    value_col = params["value_col"]
    pre_val = str(params["pre_val"])
    post_val = str(params["post_val"])
    label = params.get("intervention_label", "Intervention")

    df = df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df, pre_val = _norm_group(df, group_col, pre_val)
    df, post_val = _norm_group(df, group_col, post_val)

    # Filter to pre and post rows with non-null values
    pre_df = df[df[group_col] == pre_val][[id_col, value_col]].dropna().groupby(id_col).mean()
    post_df = df[df[group_col] == post_val][[id_col, value_col]].dropna().groupby(id_col).mean()

    all_ids = set(pre_df.index) | set(post_df.index)
    paired_ids = sorted(list(set(pre_df.index) & set(post_df.index)))
    n_pairs = len(paired_ids)
    n_dropped_unpaired = len(all_ids) - n_pairs

    if n_pairs < 2:
        raise ValueError(f"Fewer than 2 complete pairs found for paired analysis ({n_pairs} pair(s) found).")

    pre_series = pre_df.loc[paired_ids, value_col]
    post_series = post_df.loc[paired_ids, value_col]
    diffs = post_series - pre_series

    # Normality of paired differences (Shapiro-Wilk)
    _, p_shapiro = stats.shapiro(diffs[:5000]) if n_pairs >= 3 else (None, 1.0)
    normal = bool(p_shapiro is not None and p_shapiro > 0.05)

    if normal:
        res = stats.ttest_rel(post_series, pre_series)
        p_val = float(res.pvalue)
        test_used = "Paired t-test"
        effect = float(diffs.mean())
        se_diff = float(diffs.sem()) if n_pairs > 1 else 0.0
        ci = stats.t.interval(0.95, df=n_pairs - 1, loc=effect, scale=se_diff)
        eff_lo, eff_hi = float(ci[0]), float(ci[1])
        effect_label = "mean difference"
        ci_method = "Paired t interval"
    else:
        # Wilcoxon signed-rank test
        try:
            res = stats.wilcoxon(diffs, alternative="two-sided")
            p_val = float(res.pvalue)
        except ValueError:
            # All differences zero
            p_val = 1.0
        test_used = "Wilcoxon signed-rank test"
        effect = float(diffs.median())
        se_diff = float(diffs.sem()) if n_pairs > 1 else 0.0
        eff_lo = float(effect - 1.96 * se_diff)
        eff_hi = float(effect + 1.96 * se_diff)
        effect_label = "median difference"
        ci_method = "Normal-approximation interval for median difference"

    effect_label_sentence_case = effect_label[0].upper() + effect_label[1:]

    # Figure: paired lines connecting before/after points + boxplot
    fig, ax = plt.subplots(figsize=(5, 4))
    for p_val_pre, p_val_post in zip(pre_series[:200], post_series[:200]):
        ax.plot([1, 2], [p_val_pre, p_val_post], color="gray", alpha=0.35, linewidth=0.8)

    ax.boxplot(
        [pre_series, post_series],
        positions=[1, 2],
        tick_labels=[pre_val.capitalize(), post_val.capitalize()],
    )
    ax.set_ylabel(value_col)
    ax.set_title(f"{value_col} Paired Before vs. After {label}")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    fig_b64 = base64.b64encode(buf.getvalue()).decode()

    direction = "decreased" if post_series.mean() < pre_series.mean() else "increased"
    sig = "statistically significant" if p_val < 0.05 else "not statistically significant"
    shapiro_str = f"{p_shapiro:.3f}" if p_shapiro is not None else "1.000"
    methods = (
        f"A {test_used} was used to compare paired observations of {value_col} "
        f"between pre-intervention and post-intervention periods for {n_pairs} subjects with complete data in both periods. "
        f"A total of {n_dropped_unpaired} subjects were excluded because they lacked observations in both periods. "
        f"Normality of paired differences was evaluated using the Shapiro-Wilk test (p={shapiro_str}). "
        f"The {effect_label} (post minus pre) is reported with a 95% confidence interval."
    )

    result_summary = (
        f"Paired {value_col} {direction} from {pre_series.mean():.2f} (pre) to {post_series.mean():.2f} (post) across {n_pairs} pairs. "
        f"{effect_label_sentence_case} {effect:+.2f} (95% CI {eff_lo:.2f} to {eff_hi:.2f}). "
        f"{test_used}: p={p_val:.4f}. ({n_dropped_unpaired} unpaired records excluded)."
    )

    interpretation = (
        f"{value_col} {direction} from {pre_series.mean():.2f} before the intervention to {post_series.mean():.2f} after in {n_pairs} paired subjects. "
        f"The {effect_label} is {effect:+.2f} (95% CI {eff_lo:.2f} to {eff_hi:.2f}). "
        f"This difference was {sig} ({test_used}: p={p_val:.4f}). "
        f"{n_dropped_unpaired} subjects were excluded because data were not available for both periods. "
        f"[Edit this paragraph to describe what this finding means for your QI project and patients.]"
    )

    return {
        "table": [
            {"group": pre_val, "n": n_pairs, "mean": round(float(pre_series.mean()), 2), "sd": round(float(pre_series.std()), 2) if n_pairs > 1 else 0.0},
            {"group": post_val, "n": n_pairs, "mean": round(float(post_series.mean()), 2), "sd": round(float(post_series.std()), 2) if n_pairs > 1 else 0.0},
            {"group": "difference (post - pre)", "n": n_pairs, "mean": round(float(diffs.mean()), 2), "sd": round(float(diffs.std()), 2) if n_pairs > 1 else 0.0},
        ],
        "figure_base64": fig_b64,
        "methods": methods,
        "result_summary": result_summary,
        "interpretation": interpretation,
        "p_value": round(float(p_val), 4),
        "test_used": test_used,
        "effect_estimate": round(float(effect), 4),
        "effect_ci": [round(float(eff_lo), 4), round(float(eff_hi), 4)],
        "effect_label": effect_label,
        "ci_method": ci_method,
        "n_pairs": n_pairs,
        "n_dropped_unpaired": n_dropped_unpaired,
    }
