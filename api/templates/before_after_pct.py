import base64, io
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from api.stats_intervals import MIN_EXPECTED_CELL_COUNT, newcombe_rd_ci


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
            denom = ct.iloc[0, 1] * ct.iloc[1, 0]
            oddsratio = float((ct.iloc[0, 0] * ct.iloc[1, 1]) / denom) if denom else None
            test_used = "Chi-square test"
    else:
        chi2, p_value, _, _ = stats.chi2_contingency(ct)
        p_value = float(p_value)
        test_used = "Chi-square test"

    pre_pct = float(pre.mean() * 100)
    post_pct = float(post.mean() * 100)
    x_pre, n_pre_ct = int(ct.loc[pre_val, 1.0]), int(ct.loc[pre_val].sum())
    x_post, n_post_ct = int(ct.loc[post_val, 1.0]), int(ct.loc[post_val].sum())
    rd, rd_lo, rd_hi = newcombe_rd_ci(x_post, n_post_ct, x_pre, n_pre_ct)
    min_expected = float(expected.min()) if expected is not None else None

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar([pre_val.capitalize(), post_val.capitalize()], [pre_pct, post_pct],
           color=["#4C72B0", "#DD8452"])
    ax.set_ylabel("% positive")
    ax.set_title(f"{outcome_col}: Before vs. After")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    fig_b64 = base64.b64encode(buf.getvalue()).decode()

    if expected is None:
        test_reason = "expected cell counts could not be computed"
    elif test_used.startswith("Fisher"):
        test_reason = f"the smallest expected cell count was {min_expected:.1f}, below {MIN_EXPECTED_CELL_COUNT}"
    else:
        test_reason = f"all expected cell counts were {MIN_EXPECTED_CELL_COUNT} or greater"
    methods = (f"A {test_used} was used to compare the proportion of {outcome_col} "
               f"between pre- (n={len(pre)}) and post-intervention (n={len(post)}) periods; {test_reason}. "
               f"The absolute risk difference (post minus pre) is reported with a 95% confidence "
               f"interval calculated using Newcombe's hybrid score method.")
    direction = "increased" if post_pct > pre_pct else "decreased"
    sig = "statistically significant" if p_value < 0.05 else "not statistically significant"
    interpretation = (
        f"The proportion of {outcome_col} {direction} from {pre_pct:.1f}% before to {post_pct:.1f}% after the intervention. "
        f"This difference was {sig} ({test_used}: p={p_value:.4f}). "
        f"That is an absolute difference of {rd*100:+.1f} percentage points "
        f"(95% CI {rd_lo*100:.1f} to {rd_hi*100:.1f}). "
        f"[Edit this paragraph to describe what this finding means for your QI project and patients.]"
    )
    return {
        "table": [{"group": pre_val, "n": len(pre), "pct": round(pre_pct, 1)},
                  {"group": post_val, "n": len(post), "pct": round(post_pct, 1)}],
        "figure_base64": fig_b64, "methods": methods,
        "result_summary": (
            f"{outcome_col}: {pre_pct:.1f}% pre vs {post_pct:.1f}% post. "
            f"Risk difference {rd*100:+.1f} percentage points "
            f"(95% CI {rd_lo*100:.1f} to {rd_hi*100:.1f}). {test_used}: p={p_value:.4f}."
        ),
        "interpretation": interpretation,
        "p_value": round(p_value, 4), "test_used": test_used,
        "odds_ratio": round(oddsratio, 3) if oddsratio is not None else None,
        "risk_difference": round(rd, 4),
        "risk_difference_ci": [round(rd_lo, 4), round(rd_hi, 4)],
        "risk_difference_pct_points": round(rd * 100, 1),
        "risk_difference_ci_pct_points": [round(rd_lo * 100, 1), round(rd_hi * 100, 1)],
        "ci_method": "Newcombe hybrid score",
        "min_expected_cell": round(min_expected, 2) if min_expected is not None else None,
    }
