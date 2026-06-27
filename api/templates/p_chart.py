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
    pbar = float(p.mean())
    n_bar = float(agg["denom"].mean())
    ucl = float(pbar + 3 * np.sqrt(pbar * (1 - pbar) / n_bar))
    lcl = float(max(0.0, pbar - 3 * np.sqrt(pbar * (1 - pbar) / n_bar)))
    out_of_control = int(((p > ucl) | (p < lcl)).sum())

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(agg[date_col].values, (p * 100).values, marker="o", linewidth=1.5, label="Rate")
    ax.axhline(pbar * 100, color="blue", linestyle="-", label=f"Mean={pbar*100:.1f}%")
    ax.axhline(ucl * 100, color="red", linestyle="--", label=f"UCL={ucl*100:.1f}%")
    ax.axhline(lcl * 100, color="red", linestyle="--", label=f"LCL={lcl*100:.1f}%")
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
               f"Control limits were set at 3 standard deviations (UCL={ucl*100:.1f}%, LCL={lcl*100:.1f}%). "
               f"{out_of_control} point(s) fell outside control limits.")
    return {
        "table": [], "figure_base64": fig_b64, "methods": methods,
        "result_summary": f"Mean={pbar*100:.1f}%. {out_of_control} out-of-control point(s).",
        "ucl": round(ucl, 4), "lcl": round(lcl, 4), "pbar": round(pbar, 4),
    }
