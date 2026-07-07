import base64, io
from typing import Dict, Any, Tuple
import numpy as np
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


_BINARY_TRUE = {"1", "true", "t", "yes", "y", "positive", "pos"}
_BINARY_FALSE = {"0", "false", "f", "no", "n", "negative", "neg"}


def _coerce_binary_outcome(series: pd.Series, col_name: str) -> pd.Series:
    """Return a 0/1 outcome series or raise a clear error for unsupported levels."""
    coerced: list[float] = []
    unsupported: set[str] = set()
    for value in series:
        if pd.isna(value):
            coerced.append(np.nan)
            continue
        if isinstance(value, str):
            text = value.strip().lower()
            if text == "":
                coerced.append(np.nan)
            elif text in _BINARY_TRUE:
                coerced.append(1.0)
            elif text in _BINARY_FALSE:
                coerced.append(0.0)
            else:
                numeric = pd.to_numeric(text, errors="coerce")
                if pd.notna(numeric) and float(numeric) in (0.0, 1.0):
                    coerced.append(float(numeric))
                else:
                    unsupported.add(str(value))
                    coerced.append(np.nan)
            continue
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.notna(numeric) and float(numeric) in (0.0, 1.0):
            coerced.append(float(numeric))
        else:
            unsupported.add(str(value))
            coerced.append(np.nan)
    if unsupported:
        examples = ", ".join(sorted(unsupported)[:5])
        raise ValueError(
            f"Outcome column '{col_name}' must be binary (yes/no, true/false, or 0/1); unsupported values: {examples}"
        )
    return pd.Series(coerced, index=series.index, dtype="float")


def run_before_after_pct(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    group_col = params["group_col"]
    pre_val = params["pre_val"]
    post_val = params["post_val"]
    outcome_col = params["outcome_col"]

    df = df.copy()
    df, pre_val = _norm_group(df, group_col, pre_val)
    _, post_val = _norm_group(df, group_col, post_val)
    df[outcome_col] = _coerce_binary_outcome(df[outcome_col], outcome_col)

    mask = df[group_col].isin([pre_val, post_val])
    pre = df[df[group_col] == pre_val][outcome_col].dropna()
    post = df[df[group_col] == post_val][outcome_col].dropna()
    if pre.empty or post.empty:
        raise ValueError(
            f"Before/after proportion analysis requires at least one non-null binary outcome in both groups; found {len(pre)} pre and {len(post)} post"
        )

    ct = pd.crosstab(df[mask][group_col], df[mask][outcome_col])
    ct = ct.reindex(index=[pre_val, post_val], columns=[0.0, 1.0], fill_value=0)
    oddsratio = None
    expected = None
    if ct.shape == (2, 2):
        try:
            expected = stats.chi2_contingency(ct)[3]
        except ValueError:
            expected = None
        if expected is None or (expected < 5).any():
            result = stats.fisher_exact(ct)
            oddsratio, p_value = float(result[0]), float(result[1])
            test_used = "Fisher's exact test"
        else:
            chi2, p_value, _, _ = stats.chi2_contingency(ct)
            p_value = float(p_value)
            denom = ct.iloc[0, 0] * ct.iloc[1, 1]
            oddsratio = float((ct.iloc[0, 1] * ct.iloc[1, 0]) / denom) if denom else None
            test_used = "Chi-square test"
    else:
        chi2, p_value, _, _ = stats.chi2_contingency(ct)
        p_value = float(p_value)
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
    direction = "increased" if post_pct > pre_pct else "decreased"
    sig = "statistically significant" if p_value < 0.05 else "not statistically significant"
    interpretation = (
        f"The proportion of {outcome_col} {direction} from {pre_pct:.1f}% before to {post_pct:.1f}% after the intervention. "
        f"This difference was {sig} ({test_used}: p={p_value:.4f}). "
        f"[Edit this paragraph to describe what this finding means for your QI project and patients.]"
    )
    return {
        "table": [{"group": pre_val, "n": len(pre), "pct": round(pre_pct, 1)},
                  {"group": post_val, "n": len(post), "pct": round(post_pct, 1)}],
        "figure_base64": fig_b64, "methods": methods,
        "result_summary": f"{outcome_col}: {pre_pct:.1f}% pre vs {post_pct:.1f}% post. {test_used}: p={p_value:.4f}.",
        "interpretation": interpretation,
        "p_value": round(p_value, 4), "test_used": test_used,
        "odds_ratio": round(oddsratio, 3) if oddsratio is not None else None,
    }
