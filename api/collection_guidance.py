from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd

from api.models_api import ProjectDesign


def deterministic_recommendations(
    design: ProjectDesign,
    df: pd.DataFrame,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []

    # 1. outcome-column-unbound: primary_outcome is None, or its column is None / not in df.columns
    if (
        design.primary_outcome is None
        or not design.primary_outcome.column
        or design.primary_outcome.column not in df.columns
    ):
        recs.append({
            "id": "outcome-column-unbound",
            "title": "Primary outcome column is unbound",
            "why": "An outcome column must be specified and exist in your dataset to run any analysis.",
            "severity": "important",
            "necessity": "required",
            "source": "rule",
        })

    # 2. missing-denominator: primary_outcome.kind in {"proportion","rate"} and denominator_column is None
    if (
        design.primary_outcome
        and design.primary_outcome.kind in {"proportion", "rate"}
        and (not design.primary_outcome.denominator_column or design.primary_outcome.denominator_column not in df.columns)
    ):
        recs.append({
            "id": "missing-denominator",
            "title": "Denominator column needed for proportion or rate",
            "why": "Proportion and rate analyses require a denominator column (e.g. opportunities or patient days).",
            "severity": "important",
            "necessity": "required",
            "source": "rule",
        })

    # 3. no-time-column: comparison == "time-series" and time_structure.date_column is None
    if design.comparison == "time-series" and (
        not design.time_structure.date_column
        or design.time_structure.date_column not in df.columns
    ):
        recs.append({
            "id": "no-time-column",
            "title": "Date column required for time-series",
            "why": "A valid date column is required to plot data across time periods.",
            "severity": "important",
            "necessity": "required",
            "source": "rule",
        })

    # 4. no-pairing-key: design.paired is True and pairing_id_column is None
    if design.paired is True and (
        not design.pairing_id_column
        or design.pairing_id_column not in df.columns
    ):
        recs.append({
            "id": "no-pairing-key",
            "title": "Subject identifier required for paired comparison",
            "why": "Paired pre/post tests require a subject ID column that identifies the same patient across periods.",
            "severity": "important",
            "necessity": "required",
            "source": "rule",
        })

    # 5. post-only: intervention.start_date set and every parsed date falls on one side of it
    date_col = design.time_structure.date_column
    if design.intervention.present and design.intervention.start_date and date_col and date_col in df.columns:
        try:
            parsed_dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            start_dt = pd.to_datetime(design.intervention.start_date)
            if not parsed_dates.empty:
                if (parsed_dates >= start_dt).all() or (parsed_dates <= start_dt).all():
                    recs.append({
                        "id": "post-only",
                        "title": "All dates fall on one side of intervention start date",
                        "why": "Pre/post analysis requires observations both before and after the intervention date.",
                        "severity": "important",
                        "necessity": "required",
                        "source": "rule",
                    })
        except Exception:
            pass

    # 6. too-few-baseline-periods: comparison == "pre-post" and < 2 aggregated periods before intervention.start_date
    if (
        design.comparison == "pre-post"
        and design.intervention.present
        and design.intervention.start_date
        and date_col
        and date_col in df.columns
    ):
        try:
            parsed_dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            start_dt = pd.to_datetime(design.intervention.start_date)
            pre_dates = parsed_dates[parsed_dates < start_dt]
            gran = design.time_structure.granularity or "month"
            freq_map = {"day": "D", "week": "W", "month": "M", "quarter": "Q"}
            freq = freq_map.get(gran.lower(), "M")
            if pre_dates.empty or pre_dates.dt.to_period(freq).nunique() < 2:
                recs.append({
                    "id": "too-few-baseline-periods",
                    "title": "Fewer than two baseline periods before intervention",
                    "why": "At least two baseline time periods are recommended to establish a baseline before the intervention.",
                    "severity": "important",
                    "necessity": "recommended",
                    "source": "rule",
                })
        except Exception:
            pass

    # 7. too-few-time-points: time_structure.has_dates and aggregating the date column at granularity yields < 12 periods
    if design.time_structure.has_dates and date_col and date_col in df.columns:
        try:
            parsed_dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            gran = design.time_structure.granularity or "month"
            freq_map = {"day": "D", "week": "W", "month": "M", "quarter": "Q"}
            freq = freq_map.get(gran.lower(), "M")
            if not parsed_dates.empty and parsed_dates.dt.to_period(freq).nunique() < 12:
                recs.append({
                    "id": "too-few-time-points",
                    "title": "Fewer than 12 time points for statistical process control",
                    "why": "Formal control charts (P-chart, U-chart) recommend >=12 time points; a run chart will be used instead if fewer.",
                    "severity": "important",
                    "necessity": "recommended",
                    "source": "rule",
                })
        except Exception:
            pass

    # 8. no-grouping-column: design names a subgroup comparison (group_column set) but it is absent from df.columns
    if design.group_column and design.group_column not in df.columns:
        recs.append({
            "id": "no-grouping-column",
            "title": "Grouping column not found in dataset",
            "why": f"The specified comparison group column '{design.group_column}' is absent from the dataset.",
            "severity": "important",
            "necessity": "required",
            "source": "rule",
        })

    # 9. no-balancing-measure: secondary_outcomes empty
    if not design.secondary_outcomes:
        recs.append({
            "id": "no-balancing-measure",
            "title": "Consider adding a balancing measure",
            "why": "Tracking unintended consequences or balancing measures helps confirm the intervention did not cause harm elsewhere.",
            "severity": "info",
            "necessity": "optional",
            "source": "rule",
        })

    return recs
