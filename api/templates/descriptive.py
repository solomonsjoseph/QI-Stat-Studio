import pandas as pd
from api.stats_intervals import mean_ci, median_ci
from typing import Dict, Any


def run_descriptive(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    group_col = params.get("group_col")
    value_cols = params.get("value_cols", list(df.select_dtypes("number").columns))

    missing_notes = []
    table = []
    for col in value_cols:
        if col not in df.columns:
            continue
        # A selected value_col is not guaranteed to already be numeric
        # dtype (e.g. a zip-code-shaped numeric measure preserved as text
        # on upload to protect a real identifier column elsewhere in the
        # same file); .mean()/.std() on a string Series raises instead of
        # producing a result, so coerce defensively before using it.
        col_series = pd.to_numeric(df[col], errors="coerce")
        pct_miss = col_series.isna().mean() * 100
        if pct_miss > 0:
            missing_notes.append(f"{col} ({pct_miss:.1f}% missing)")
        if group_col and group_col in df.columns:
            grp_col = df[group_col].str.strip().str.lower() if df[group_col].dtype == object else df[group_col]
            for grp, sub in df.groupby(grp_col):
                sub_vals = col_series.loc[sub.index]
                display_group = str(sub[group_col].iloc[0]) if df[group_col].dtype == object else str(grp)
                mean_lo, mean_hi = mean_ci(sub_vals)
                median_lo, median_hi = median_ci(sub_vals)
                table.append({"group": display_group, "variable": col,
                               "n": int(sub_vals.notna().sum()),
                               "mean": round(sub_vals.mean(), 2),
                               "sd": round(sub_vals.std(), 2),
                               "median": round(sub_vals.median(), 2),
                               "mean_ci_low": round(mean_lo, 2) if mean_lo is not None else None,
                               "mean_ci_high": round(mean_hi, 2) if mean_hi is not None else None,
                               "median_ci_low": round(median_lo, 2) if median_lo is not None else None,
                               "median_ci_high": round(median_hi, 2) if median_hi is not None else None})
        else:
            mean_lo, mean_hi = mean_ci(col_series)
            median_lo, median_hi = median_ci(col_series)
            table.append({"group": "All", "variable": col,
                           "n": int(col_series.notna().sum()),
                           "mean": round(col_series.mean(), 2),
                           "sd": round(col_series.std(), 2),
                           "median": round(col_series.median(), 2),
                           "mean_ci_low": round(mean_lo, 2) if mean_lo is not None else None,
                           "mean_ci_high": round(mean_hi, 2) if mean_hi is not None else None,
                           "median_ci_low": round(median_lo, 2) if median_lo is not None else None,
                           "median_ci_high": round(median_hi, 2) if median_hi is not None else None})

    miss_str = (f" Note: {', '.join(missing_notes)} had missing values excluded."
                if missing_notes else "")
    methods = (f"Descriptive statistics were calculated for {len(value_cols)} variable(s). "
               f"Continuous variables are reported as mean ± SD and median.{miss_str} "
               f"Means are reported with a 95% t-based confidence interval and medians with a distribution-free "
               f"interval from order statistics; intervals are omitted where the group has too few values to "
               f"support one.")
    n_groups = df[group_col].nunique() if group_col and group_col in df.columns else 1
    interpretation = (
        f"The descriptive analysis summarized {len(value_cols)} variable(s) across {n_groups} group(s). "
        f"{'Missing data were observed in: ' + ', '.join(missing_notes) + '.' if missing_notes else 'No missing data were observed in the selected variables.'} "
        f"[Edit this paragraph to describe what the findings mean for your QI project.]"
    )
    return {"table": table, "figure_base64": None, "methods": methods,
            "result_summary": f"Descriptive summary of {len(value_cols)} variable(s) across {n_groups} group(s).",
            "interpretation": interpretation}
