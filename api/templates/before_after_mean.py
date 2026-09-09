import base64, io
from typing import Dict, Any, Tuple
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from api.stats_intervals import HL_SUBSAMPLE_PER_GROUP, hodges_lehmann_ci, mean_diff_ci


def _norm_group(df: pd.DataFrame, col: str, val: str) -> Tuple[pd.DataFrame, str]:
    """Normalize string group column to lowercase stripped — handles mixed-case period values."""
    if df[col].dtype == object:
        df = df.copy()
        df[col] = df[col].str.strip().str.lower()
        val = val.strip().lower()
    return df, val


def run_before_after_mean(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    group_col = params["group_col"]
    pre_val = params["pre_val"]
    post_val = params["post_val"]
    value_col = params["value_col"]
    label = params.get("intervention_label", "Intervention")

    df = df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df, pre_val = _norm_group(df, group_col, pre_val)
    _, post_val = _norm_group(df, group_col, post_val)
    in_group = df[group_col].isin([pre_val, post_val])
    n_excluded_other_group = int((~in_group).sum())
    selected = df[in_group]
    n_excluded_missing = int(selected[value_col].isna().sum())
    pre = df[df[group_col] == pre_val][value_col].dropna()
    post = df[df[group_col] == post_val][value_col].dropna()

    # Shapiro-Wilk normality + Levene variance test
    _, p_shapiro_pre = stats.shapiro(pre[:5000]) if len(pre) >= 3 else (None, 0.0)
    _, p_shapiro_post = stats.shapiro(post[:5000]) if len(post) >= 3 else (None, 0.0)
    _, p_levene = stats.levene(pre, post)
    normal = p_shapiro_pre > 0.05 and p_shapiro_post > 0.05

    if normal and p_levene > 0.05:
        _, p_value = stats.ttest_ind(pre, post)
        test_used = "Two-sample t-test"
        effect, eff_lo, eff_hi = mean_diff_ci(pre, post)
        effect_label, subsampled = "difference in means", False
    else:
        _, p_value = stats.mannwhitneyu(pre, post, alternative="two-sided")
        test_used = "Wilcoxon rank-sum test"
        effect, eff_lo, eff_hi, subsampled = hodges_lehmann_ci(pre, post)
        effect_label = "median difference (Hodges-Lehmann)"
    effect_label_sentence_case = effect_label[0].upper() + effect_label[1:]

    # Boxplot
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.boxplot([pre, post], tick_labels=[pre_val.capitalize(), post_val.capitalize()])
    ax.set_ylabel(value_col)
    ax.set_title(f"{value_col} Before vs. After {label}")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    fig_b64 = base64.b64encode(buf.getvalue()).decode()

    exclusion_note = (
        f" {n_excluded_missing} record{' was' if n_excluded_missing == 1 else 's were'} excluded "
        f"because {value_col} was missing or could not be parsed."
        + (
            f" {n_excluded_other_group} record{' was' if n_excluded_other_group == 1 else 's were'} excluded "
            f"because {group_col} did not match either the pre- or post-intervention label."
            if n_excluded_other_group else ""
        )
    )
    methods = (
        f"An independent samples {test_used} was used to compare {value_col} "
        f"between the pre-intervention (n={len(pre)}) and post-intervention (n={len(post)}) periods. "
        f"Normality was assessed using the Shapiro-Wilk test "
        f"(pre p={p_shapiro_pre:.3f}, post p={p_shapiro_post:.3f}); "
        f"variance equality was assessed using Levene's test (p={p_levene:.3f})."
        f" The {effect_label} (post minus pre) is reported with a 95% confidence interval."
        + (f" The interval was computed from a systematic sample of {HL_SUBSAMPLE_PER_GROUP} values per "
           f"period because the full pairwise comparison exceeded the computation limit." if subsampled else "")
        + exclusion_note
    )
    direction = "decreased" if post.mean() < pre.mean() else "increased"
    result_summary = (
        f"{value_col} {direction} from {pre.mean():.2f} (pre) to {post.mean():.2f} (post). "
        f"{effect_label_sentence_case} {effect:+.2f} (95% CI {eff_lo:.2f} to {eff_hi:.2f}). "
        f"{test_used}: p={p_value:.4f}.{exclusion_note}"
    )

    sig = "statistically significant" if float(p_value) < 0.05 else "not statistically significant"
    interpretation = (
        f"{value_col} {direction} from {pre.mean():.2f} before the intervention to {post.mean():.2f} after. "
        f"The {effect_label} is {effect:+.2f} (95% CI {eff_lo:.2f} to {eff_hi:.2f}). "
        f"This difference was {sig} ({test_used}: p={float(p_value):.4f}).{exclusion_note} "
        f"[Edit this paragraph to describe what this finding means for your QI project and patients.]"
    )
    return {
        "table": [
            {"group": pre_val, "n": len(pre), "mean": round(pre.mean(), 2), "sd": round(pre.std(), 2)},
            {"group": post_val, "n": len(post), "mean": round(post.mean(), 2), "sd": round(post.std(), 2)},
        ],
        "figure_base64": fig_b64,
        "methods": methods,
        "result_summary": result_summary,
        "interpretation": interpretation,
        "p_value": round(float(p_value), 4),
        "test_used": test_used,
        "effect_estimate": round(float(effect), 4),
        "effect_ci": [round(float(eff_lo), 4), round(float(eff_hi), 4)],
        "effect_label": effect_label,
        "ci_method": "Pooled-variance t interval" if test_used == "Two-sample t-test" else "Hodges-Lehmann with Moses interval",
        "n_excluded_missing": n_excluded_missing,
        "n_excluded_other_group": n_excluded_other_group,
    }
