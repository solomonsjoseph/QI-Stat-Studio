import base64, io
from typing import Dict, Any
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def run_p_chart(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    date_col = params["date_col"]
    numerator_col = params["numerator_col"]
    denominator_col = params.get("denominator_col")
    intervention_date = params.get("intervention_date")
    freq = params.get("freq", "ME")

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df[numerator_col] = pd.to_numeric(df[numerator_col], errors="coerce")

    if denominator_col:
        df[denominator_col] = pd.to_numeric(df[denominator_col], errors="coerce")
        agg = df.set_index(date_col).resample(freq).agg(
            num=(numerator_col, "sum"), denom=(denominator_col, "sum")
        ).dropna().reset_index()
    else:
        agg = df.set_index(date_col).resample(freq).agg(
            num=(numerator_col, "sum"), denom=(numerator_col, "count")
        ).dropna().reset_index()

    p = agg["num"] / agg["denom"]
    pbar = float(agg["num"].sum() / agg["denom"].sum())
    sigma = np.sqrt(pbar * (1 - pbar) / agg["denom"])
    ucl = pbar + 3 * sigma
    lcl = (pbar - 3 * sigma).clip(lower=0.0)
    out_of_control = int(((p > ucl) | (p < lcl)).sum())

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(agg[date_col].values, (p * 100).values, marker="o", linewidth=1.5, label="Rate")
    ax.axhline(pbar * 100, color="blue", linestyle="-", label=f"Mean={pbar*100:.1f}%")
    ax.step(agg[date_col].values, (ucl * 100).values, where="mid", color="red", linestyle="--", label="UCL")
    ax.step(agg[date_col].values, (lcl * 100).values, where="mid", color="red", linestyle="--", label="LCL")
    if intervention_date:
        ax.axvline(pd.to_datetime(intervention_date).to_datetime64(), color="green", linestyle=":", linewidth=2, label="Intervention")
    denom_label = denominator_col or "n"
    ax.set_title(f"p-Chart — {numerator_col}/{denom_label}")
    ax.set_ylabel("Proportion (%)")
    ax.set_xlabel(date_col)
    ax.legend()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    fig_b64 = base64.b64encode(buf.getvalue()).decode()

    methods = (f"A p-chart (control chart for proportions) was constructed using {len(agg)} time points. "
               f"Control limits were set at 3 standard deviations using each period's denominator. "
               f"{out_of_control} point(s) fell outside control limits.")
    oc_phrase = (f"{out_of_control} point(s) fell outside the 3-sigma control limits, indicating special-cause variation."
                 if out_of_control else "All points fell within control limits, indicating the process was in statistical control.")
    interpretation = (
        f"The p-chart shows the proportion of {numerator_col} over {len(agg)} time periods. "
        f"The overall mean rate was {pbar*100:.1f}%. "
        f"{oc_phrase} "
        f"[Edit this paragraph to describe what this pattern means for your QI project.]"
    )
    return {
        "table": [], "figure_base64": fig_b64, "methods": methods,
        "result_summary": f"Mean={pbar*100:.1f}%. {out_of_control} out-of-control point(s).",
        "interpretation": interpretation,
        "ucl": [round(float(value), 4) for value in ucl], "lcl": [round(float(value), 4) for value in lcl], "pbar": round(pbar, 4),
    }
