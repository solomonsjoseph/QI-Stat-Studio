"""Downgrade a control chart request to a run chart below 12 time points.

Scope: the downgrade and its Methods sentence only. No on-screen notice and
no confirmation gate here; whether the resident is told their 12-point
estimate was wrong is one of the round-2 questions still unanswered.
"""

from __future__ import annotations

import pandas as pd

from api.analysis_validation import aggregate_control_chart_frame

MIN_CONTROL_CHART_POINTS = 12

_NUMERATOR_FIELD = {"p_chart": "numerator_col", "u_c_chart": "count_col"}

_SPELLED_COUNTS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
]


def spell_count(n: int) -> str:
    """Spell 0 through 9; return the digits for 10 and above."""
    if 0 <= n < len(_SPELLED_COUNTS):
        return _SPELLED_COUNTS[n]
    return str(n)


def downgrade_note(observed: int) -> str:
    return (
        f"A run chart was used rather than a control chart because {spell_count(observed)} "
        f"time {'point was' if observed == 1 else 'points were'} available; "
        f"control limits require at least 12 time points."
    )


def maybe_downgrade_control_chart(
    template: str, df: pd.DataFrame, params: dict
) -> tuple[str, pd.DataFrame, dict, int | None]:
    """Downgrade a p_chart/u_c_chart request with fewer than 12 aggregated time points.

    Returns the inputs unchanged (with a None downgrade count) for every other
    template, and on any aggregation failure -- a malformed date column then
    surfaces as the normal parse error from validate_analysis_inputs rather
    than becoming a silent downgrade.
    """
    numerator_field = _NUMERATOR_FIELD.get(template)
    if numerator_field is None:
        return template, df, params, None

    try:
        agg = aggregate_control_chart_frame(df, params, numerator_field)
    except (ValueError, TypeError, KeyError):
        return template, df, params, None

    if len(agg) >= MIN_CONTROL_CHART_POINTS:
        return template, df, params, None

    date_col = params["date_col"]
    if template == "p_chart":
        numerator_col = params["numerator_col"]
        value_col = f"{numerator_col} proportion"
        agg[value_col] = agg["num"] / agg["denom"]
    else:
        count_col = params["count_col"]
        denominator_col = params.get("denominator_col")
        value_col = f"{count_col} rate" if denominator_col else count_col
        agg[value_col] = agg["num"] / agg["denom"] if denominator_col else agg["num"]

    new_df = agg[[date_col, value_col]]
    new_params: dict = {
        "date_col": date_col,
        "value_col": value_col,
        "design_note": downgrade_note(len(agg)),
    }
    if params.get("intervention_date") is not None:
        new_params["intervention_date"] = params["intervention_date"]
    if params.get("freq") is not None:
        new_params["freq"] = params["freq"]
    return "run_chart", new_df, new_params, len(agg)
