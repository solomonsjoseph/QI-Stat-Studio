import base64, io
from typing import Dict, Any, Tuple
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats


def _norm_group(df: pd.DataFrame, col: str, val: str) -> Tuple[pd.DataFrame, str]:
    if df[col].dtype == object:
        df = df.copy()
        df[col] = df[col].str.strip().str.lower()
        val = val.strip().lower()
    return df, val


def run_before_after_pct(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    group_col = params["group_col"]
    pre_val = params["pre_val"]
    post_val = params["post_val"]
    outcome_col = params["outcome_col"]

    df = df.copy()
    df, pre_val = _norm_group(df, group_col, pre_val)
    _, post_val = _norm_group(df, group_col, post_val)
    df[outcome_col] = pd.to_numeric(df[outcome_col], errors="coerce")

    mask = df[group_col].isin([pre_val, post_val])
    pre = df[df[group_col] == pre_val][outcome_col].dropna()
    post = df[df[group_col] == post_val][outcome_col].dropna()

    ct = pd.crosstab(df[mask][group_col], df[mask][outcome_col])
    expected = stats.chi2_contingency(ct)[3]
    oddsratio = None
    if (expected < 5).any():
        result = stats.fisher_exact(ct)
        oddsratio, p_value = float(result[0]), float(result[1])
        test_used = "Fisher's exact test"
    else:
        chi2, p_value, _, _ = stats.chi2_contingency(ct)
        p_value = float(p_value)
        if ct.shape == (2, 2):
            oddsratio = float((ct.iloc[0, 1] / ct.iloc[0, 0]) / (ct.iloc[1, 1] / ct.iloc[1, 0]))
        test_used = "Chi-square test"

    pre_pct = float(pre.mean() * 100)
    post_pct = float(post.mean() * 100)

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar([pre_val.capitalize(), post_val.capitalize()], [pre_pct, post_pct],
           color=["#4C72B0", "#DD8452"])
    ax.set_ylabel("% positive")
    ax.set_title(f"{outcome_col}: Before vs. After")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    fig_b64 = base64.b64encode(buf.getvalue()).decode()

    methods = (f"A {test_used} was used to compare the proportion of {outcome_col} "
               f"between pre- (n={len(pre)}) and post-intervention (n={len(post)}) periods.")
    return {
        "table": [{"group": pre_val, "n": len(pre), "pct": round(pre_pct, 1)},
                  {"group": post_val, "n": len(post), "pct": round(post_pct, 1)}],
        "figure_base64": fig_b64, "methods": methods,
        "result_summary": f"{outcome_col}: {pre_pct:.1f}% pre vs {post_pct:.1f}% post. {test_used}: p={p_value:.4f}.",
        "p_value": round(p_value, 4), "test_used": test_used,
        "odds_ratio": round(oddsratio, 3) if oddsratio is not None else None,
    }
