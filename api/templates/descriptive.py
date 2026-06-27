import pandas as pd
from typing import Dict, Any


def run_descriptive(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    group_col = params.get("group_col")
    value_cols = params.get("value_cols", list(df.select_dtypes("number").columns))

    missing_notes = []
    table = []
    for col in value_cols:
        if col not in df.columns:
            continue
        pct_miss = df[col].isna().mean() * 100
        if pct_miss > 0:
            missing_notes.append(f"{col} ({pct_miss:.1f}% missing)")
        if group_col and group_col in df.columns:
            grp_col = df[group_col].str.strip().str.lower() if df[group_col].dtype == object else df[group_col]
            for grp, sub in df.groupby(grp_col):
                table.append({"group": str(grp), "variable": col,
                               "n": int(sub[col].notna().sum()),
                               "mean": round(sub[col].mean(), 2),
                               "sd": round(sub[col].std(), 2),
                               "median": round(sub[col].median(), 2)})
        else:
            table.append({"group": "All", "variable": col,
                           "n": int(df[col].notna().sum()),
                           "mean": round(df[col].mean(), 2),
                           "sd": round(df[col].std(), 2),
                           "median": round(df[col].median(), 2)})

    miss_str = (f" Note: {', '.join(missing_notes)} had missing values excluded."
                if missing_notes else "")
    methods = (f"Descriptive statistics were calculated for {len(value_cols)} variable(s). "
               f"Continuous variables are reported as mean ± SD and median.{miss_str}")
    n_groups = df[group_col].nunique() if group_col and group_col in df.columns else 1
    return {"table": table, "figure_base64": None, "methods": methods,
            "result_summary": f"Descriptive summary of {len(value_cols)} variable(s) across {n_groups} group(s)."}
