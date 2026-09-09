import base64, io
from typing import Dict, Any
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def run_u_c_chart(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    date_col = params["date_col"]
    count_col = params["count_col"]
    denominator_col = params.get("denominator_col")
    intervention_date = params.get("intervention_date")
    freq = params.get("freq", "ME")
    chart_type = "u" if denominator_col else "c"

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df[count_col] = pd.to_numeric(df[count_col], errors="coerce")
    n_input_records = len(df)
    stable_denominator = False

    required_cols = [count_col]
    if denominator_col:
        df[denominator_col] = pd.to_numeric(df[denominator_col], errors="coerce")
        required_cols.append(denominator_col)
    n_excluded_missing = int(df[required_cols].isna().any(axis=1).sum())
    period_input_counts = df.set_index(date_col).resample(freq).size()
    df = df.dropna(subset=required_cols)
    n_included_records = len(df)

    if denominator_col:
        agg = df.set_index(date_col).resample(freq).agg(
            cnt=(count_col, "sum"), denom=(denominator_col, "sum"), n=(count_col, "count")
        ).dropna()
        agg = agg[agg["n"] > 0].drop(columns="n").reset_index()
        stable_denominator = agg["denom"].nunique() <= 1
        chart_type = "c" if stable_denominator else "u"
    else:
        agg = df.set_index(date_col).resample(freq).agg(
            cnt=(count_col, "sum"), n=(count_col, "count")
        ).dropna()
        agg = agg[agg["n"] > 0].drop(columns="n").reset_index()

    n_excluded_calendar_gaps = int((period_input_counts == 0).sum())

    if chart_type == "u":
        y = agg["cnt"] / agg["denom"]
        ubar = float(agg["cnt"].sum() / agg["denom"].sum())
        sigma = np.sqrt(ubar / agg["denom"])
        ucl = ubar + 3 * sigma
        lcl = (ubar - 3 * sigma).clip(lower=0.0)
        ylabel = "Rate"
    else:
        cbar = float(agg["cnt"].mean())
        ucl = pd.Series(cbar + 3 * np.sqrt(cbar), index=agg.index)
        lcl = pd.Series(max(0.0, cbar - 3 * np.sqrt(cbar)), index=agg.index)
        ubar = cbar
        y = agg["cnt"]
        ylabel = "Count"

    plot_dates = agg[date_col]

    out_of_control = int(((y > ucl) | (y < lcl)).sum())

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(plot_dates.values, y.values, marker="o", linewidth=1.5)
    ax.axhline(ubar, color="blue", linestyle="-", label=f"Mean={ubar:.3f}")
    ax.step(plot_dates.values, ucl.values, where="mid", color="red", linestyle="--", label="UCL")
    ax.step(plot_dates.values, lcl.values, where="mid", color="red", linestyle="--", label="LCL")
    if intervention_date:
        ax.axvline(pd.to_datetime(intervention_date).to_datetime64(), color="green", linestyle=":", linewidth=2, label="Intervention")
    ax.set_title(f"{'u' if chart_type == 'u' else 'c'}-Chart — {count_col}")
    ax.set_ylabel(ylabel)
    ax.set_xlabel(date_col)
    ax.legend()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    fig_b64 = base64.b64encode(buf.getvalue()).decode()

    if chart_type == "u":
        limit_note = "Control limits were set at 3 standard deviations using each period's denominator."
    elif stable_denominator:
        limit_note = "The denominator is stable across periods, so a c-chart was used. Control limits were set at 3 standard deviations."
    else:
        limit_note = "Control limits were set at 3 standard deviations."
    exclusion_notes = []
    if n_excluded_missing:
        exclusion_notes.append(
            f"{n_excluded_missing} record{' was' if n_excluded_missing == 1 else 's were'} excluded "
            "because count or denominator values were missing or invalid."
        )
    if n_excluded_calendar_gaps:
        exclusion_notes.append(
            f"{n_excluded_calendar_gaps} calendar period{' was' if n_excluded_calendar_gaps == 1 else 's were'} "
            "excluded because no uploaded rows were present."
        )
    exclusion_note = f" {' '.join(exclusion_notes)}" if exclusion_notes else ""
    methods = (f"A {'u' if chart_type == 'u' else 'c'}-chart was constructed for {count_col} "
               f"across {len(agg)} time points. {limit_note} "
               f"{out_of_control} point(s) fell outside control limits.{exclusion_note}")
    oc_phrase = (f"{out_of_control} point(s) fell outside control limits, indicating special-cause variation."
                 if out_of_control else "All points fell within control limits, indicating the process was in statistical control.")
    chart_label = "u-chart (rate)" if chart_type == "u" else "c-chart (count)"
    interpretation = (
        f"The {chart_label} shows {count_col} over {len(agg)} time periods with a mean of {ubar:.3f}. "
        f"{oc_phrase}{exclusion_note} "
        f"[Edit this paragraph to describe what this pattern means for your QI project.]"
    )
    return {
        "table": [], "figure_base64": fig_b64, "methods": methods,
        "result_summary": f"Mean={ubar:.3f}. {out_of_control} out-of-control point(s).{exclusion_note}",
        "interpretation": interpretation,
        "chart_type": chart_type,
        "ucl": [round(float(value), 4) for value in ucl], "lcl": [round(float(value), 4) for value in lcl],
        "n_input_records": n_input_records,
        "n_included_records": n_included_records,
        "n_excluded_missing": n_excluded_missing,
        "n_excluded_calendar_gaps": n_excluded_calendar_gaps,
    }
