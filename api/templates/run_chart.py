import base64, io
from typing import Dict, Any
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def run_run_chart(df: pd.DataFrame, params: dict) -> Dict[str, Any]:
    date_col = params["date_col"]
    value_col = params["value_col"]
    intervention_date = params.get("intervention_date")
    freq = params.get("freq", "ME")

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col)[value_col].resample(freq).mean().dropna().reset_index()
    df = df.sort_values(date_col)
    median = float(df[value_col].median())

    sides = (df[value_col] > median).astype(int)
    max_run = 0
    cur_run = 1
    for i in range(1, len(sides)):
        if sides.iloc[i] == sides.iloc[i - 1]:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1
    signal = max_run >= 8

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(df[date_col].values, df[value_col].values, marker="o", linewidth=1.5)
    ax.axhline(median, color="red", linestyle="--", label=f"Median={median:.2f}")
    if intervention_date:
        ax.axvline(pd.to_datetime(intervention_date).to_datetime64(), color="green", linestyle=":", linewidth=2, label="Intervention")
    title = f"Run Chart — {value_col}"
    if signal:
        title += " ⚠ Signal detected (run ≥8)"
    ax.set_title(title)
    ax.legend()
    ax.set_xlabel(date_col)
    ax.set_ylabel(value_col)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    fig_b64 = base64.b64encode(buf.getvalue()).decode()

    methods = (f"A run chart was constructed for {value_col} over time. "
               f"The median ({median:.2f}) is shown as a reference line. "
               f"A run signal (≥8 consecutive points on the same side of the median) "
               f"{'was' if signal else 'was not'} detected.")
    return {
        "table": [], "figure_base64": fig_b64, "methods": methods,
        "result_summary": f"Median={median:.2f}. Signal {'detected' if signal else 'not detected'} (longest run={max_run}).",
        "signal_detected": signal, "max_run": max_run,
    }
