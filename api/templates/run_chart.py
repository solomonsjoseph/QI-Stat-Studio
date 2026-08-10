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

    median_tie_count = int((df[value_col] == median).sum())
    non_tie_values = df.loc[df[value_col] != median, value_col]
    sides = (non_tie_values > median).astype(int)
    max_run = 0
    cur_run = 0
    prev_side = None
    for side in sides:
        if prev_side is None or side != prev_side:
            cur_run = 1
        else:
            cur_run += 1
        max_run = max(max_run, cur_run)
        prev_side = side
    signal = max_run >= 8

    max_trend = 1 if len(df) else 0
    cur_trend = 1
    trend_direction = 0
    values = df[value_col].tolist()
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        direction = 1 if diff > 0 else -1 if diff < 0 else 0
        if direction == 0:
            cur_trend = 1
            trend_direction = 0
        elif direction == trend_direction:
            cur_trend += 1
        else:
            cur_trend = 2
            trend_direction = direction
        max_trend = max(max_trend, cur_trend)
    trend_signal = max_trend >= 6

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
               f"Median ties (n={median_tie_count}) were excluded from run calculations. "
               f"A run signal (≥8 consecutive non-tie points on the same side of the median) "
               f"{'was' if signal else 'was not'} detected. "
               f"A trend signal (≥6 consecutive increases or decreases) "
               f"{'was' if trend_signal else 'was not'} detected.")
    design_note = params.get("design_note")
    if design_note:
        methods = f"{design_note} {methods}"
    interpretation = (
        f"The run chart shows {value_col} over time with a median of {median:.2f}. "
        f"{'A run signal was detected (longest run = ' + str(max_run) + ' consecutive points on the same side of the median), suggesting a non-random shift in the process.' if signal else 'No run signal was detected (longest run = ' + str(max_run) + '), suggesting the process remained stable during the observation period.'} "
        f"[Edit this paragraph to describe what this pattern means for your QI project.]"
    )
    return {
        "table": [], "figure_base64": fig_b64, "methods": methods,
        "result_summary": f"Median={median:.2f}. Signal {'detected' if signal else 'not detected'} (longest run={max_run}).",
        "interpretation": interpretation,
        "signal_detected": signal, "max_run": max_run,
        "trend_signal_detected": trend_signal, "max_trend": max_trend,
        "median_tie_count": median_tie_count,
    }
