"""Deterministic analysis-plan proposer.

Maps a confirmed ProjectDesign + upload profile onto the fixed template library.
The resident remains the only authority that can confirm a plan; this module only drafts.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import pandas as pd

from api.models_api import AnalysisPlanItem, ProjectDesign

Confidence = Literal["high", "medium", "low"]

# Clinical-owner-reviewable defaults: design shape → which library templates to propose.
# Keep this table explicit; do not hide method policy inside an LLM prompt.
_DISPLAY: dict[str, tuple[str, str, str]] = {
    "descriptive_summary": (
        "Summary statistics",
        "What do the key measures look like overall?",
        "Summarizes counts, averages, and percentages. Best for one time period or group.",
    ),
    "before_after_mean": (
        "Average comparison (t-test / Wilcoxon)",
        "Did the average outcome change between periods or groups?",
        "Compares an average value between two periods using a t-test or Wilcoxon test.",
    ),
    "before_after_pct": (
        "Percentage comparison (chi-square / Fisher)",
        "Did the proportion of the outcome change between periods or groups?",
        "Compares a proportion between two periods using chi-square or Fisher's exact test.",
    ),
    "before_after_paired": (
        "Paired before/after comparison",
        "Did each subject's outcome change from before to after?",
        "Compares each subject's before and after value when the same subjects appear in both periods.",
    ),
    "run_chart": (
        "Run chart over time",
        "How does the measure trend across time periods?",
        "Line chart over time with median and run signals. Useful with fewer than 12 time points.",
    ),
    "p_chart": (
        "Percentage over time (P chart)",
        "Did the proportion show special-cause variation over time?",
        "Control chart for proportions with 3-sigma limits. Prefer when you have 12 or more time points.",
    ),
    "u_c_chart": (
        "Rate or count over time (U/C chart)",
        "Did the rate or count show special-cause variation over time?",
        "Control chart for rates or counts with 3-sigma limits. Prefer when you have 12 or more time points.",
    ),
}


def _field_confidence(design: ProjectDesign, path: str, *, bound: bool) -> Confidence:
    if not bound:
        return "low"
    status = (design.status or {}).get(path)
    if status in ("user-confirmed", "user-corrected"):
        return "high"
    if status == "inferred":
        return "medium"
    prior = (design.confidence or {}).get(path)
    if prior in ("high", "medium", "low"):
        return prior  # type: ignore[return-value]
    return "medium"


def _first_role(profile: dict[str, Any], *roles: str) -> str | None:
    candidate_roles = profile.get("candidate_roles") or {}
    for role in roles:
        cols = candidate_roles.get(role) or []
        if cols:
            return str(cols[0])
    return None


def _column_exists(df: pd.DataFrame, name: str | None) -> bool:
    return bool(name) and name in df.columns


def _templates_for_design(design: ProjectDesign) -> list[str]:
    """Return ordered template ids suggested by the design. Clinical mapping table."""
    kind = design.primary_outcome.kind if design.primary_outcome else "unknown"
    has_dates = bool(design.time_structure.has_dates or design.time_structure.date_column)
    comparison = design.comparison
    paired = design.paired is True
    suggested: list[str] = []

    # Baseline picture whenever an outcome is in play.
    suggested.append("descriptive_summary")

    # Pre/post or between-group comparisons.
    if comparison in ("pre-post", "between-group") or (
        design.group_column and comparison != "time-series"
    ):
        if paired:
            suggested.append("before_after_paired")
        elif kind in ("proportion", "binary"):
            suggested.append("before_after_pct")
        else:
            # continuous, count, rate, unknown → mean comparison as the default
            suggested.append("before_after_mean")
            if kind == "unknown":
                suggested.append("before_after_pct")

    # Time-oriented views.
    if has_dates or comparison == "time-series":
        if kind in ("proportion", "binary"):
            suggested.extend(["p_chart", "run_chart"])
        elif kind in ("rate", "count"):
            suggested.extend(["u_c_chart", "run_chart"])
        else:
            suggested.append("run_chart")
            if kind in ("unknown", "continuous"):
                suggested.append("u_c_chart")

    return list(dict.fromkeys(suggested))


def _bind_descriptive(
    design: ProjectDesign, profile: dict[str, Any], df: pd.DataFrame
) -> tuple[dict[str, Any], dict[str, Confidence]]:
    params: dict[str, Any] = {}
    conf: dict[str, Confidence] = {}
    cols: list[str] = []

    outcome_col = design.primary_outcome.column if design.primary_outcome else None
    if _column_exists(df, outcome_col):
        cols.append(outcome_col)  # type: ignore[arg-type]
        conf["value_cols"] = _field_confidence(design, "primary_outcome.column", bound=True)
    else:
        fallback = _first_role(profile, "outcome", "numerator")
        if _column_exists(df, fallback):
            cols.append(fallback)  # type: ignore[arg-type]
            conf["value_cols"] = "low"
        else:
            numeric = [
                c["name"] for c in profile.get("columns", []) if c.get("inferred_type") == "Number"
            ]
            cols = [c for c in numeric if c in df.columns][:3]
            conf["value_cols"] = "low"

    if cols:
        params["value_cols"] = cols

    group = (
        design.group_column
        if _column_exists(df, design.group_column)
        else _first_role(profile, "grouping")
    )
    if _column_exists(df, group):
        params["group_col"] = group
        conf["group_col"] = (
            _field_confidence(design, "group_column", bound=True)
            if group == design.group_column
            else "low"
        )
    return params, conf


_PRE_RE = re.compile(r"^(pre|before|baseline|control|usual care)\b")
_POST_RE = re.compile(r"^(post|after|intervention|follow[- ]?up)\b")


def _guess_pre_post(col: pd.Series) -> tuple[str | None, str | None]:
    """Pre and post labels when the column has exactly two levels (case and padding ignored) that read like them."""
    levels = col.dropna().astype(str).str.strip().str.lower().unique().tolist()
    if len(levels) != 2:
        return None, None
    pre = [v for v in levels if _PRE_RE.match(v)]
    post = [v for v in levels if _POST_RE.match(v)]
    return (pre[0], post[0]) if len(pre) == 1 and len(post) == 1 else (None, None)


def _bind_before_after_mean(
    design: ProjectDesign, profile: dict[str, Any], df: pd.DataFrame
) -> tuple[dict[str, Any], dict[str, Confidence]]:
    params: dict[str, Any] = {}
    conf: dict[str, Confidence] = {}

    group = (
        design.group_column
        if _column_exists(df, design.group_column)
        else _first_role(profile, "grouping")
    )
    value = (
        design.primary_outcome.column
        if design.primary_outcome and _column_exists(df, design.primary_outcome.column)
        else _first_role(profile, "outcome", "numerator")
    )
    if _column_exists(df, group):
        params["group_col"] = group
        conf["group_col"] = (
            _field_confidence(design, "group_column", bound=True)
            if group == design.group_column
            else "low"
        )
    if _column_exists(df, value):
        params["value_col"] = value
        conf["value_col"] = (
            _field_confidence(design, "primary_outcome.column", bound=True)
            if design.primary_outcome and value == design.primary_outcome.column
            else "low"
        )

    pre, post = design.pre_label, design.post_label
    if not (pre and post) and _column_exists(df, group):
        guessed = _guess_pre_post(df[group])
        pre, post = pre or guessed[0], post or guessed[1]
    if pre:
        params["pre_val"] = pre
        conf["pre_val"] = _field_confidence(design, "pre_label", bound=True) if design.pre_label else "medium"
    if post:
        params["post_val"] = post
        conf["post_val"] = _field_confidence(design, "post_label", bound=True) if design.post_label else "medium"
    return params, conf


def _bind_before_after_pct(
    design: ProjectDesign, profile: dict[str, Any], df: pd.DataFrame
) -> tuple[dict[str, Any], dict[str, Confidence]]:
    params, conf = _bind_before_after_mean(design, profile, df)
    if "value_col" in params:
        params["outcome_col"] = params.pop("value_col")
        conf["outcome_col"] = conf.pop("value_col", "low")
    return params, conf


def _bind_before_after_paired(
    design: ProjectDesign, profile: dict[str, Any], df: pd.DataFrame
) -> tuple[dict[str, Any], dict[str, Confidence]]:
    params, conf = _bind_before_after_mean(design, profile, df)
    id_col = (
        design.pairing_id_column
        if _column_exists(df, design.pairing_id_column)
        else _first_role(profile, "pairing_id", "identifier")
    )
    if _column_exists(df, id_col):
        params["id_col"] = id_col
        conf["id_col"] = (
            _field_confidence(design, "pairing_id_column", bound=True)
            if id_col == design.pairing_id_column
            else "low"
        )
    return params, conf


_FREQ_BY_GRANULARITY = {"day": "D", "week": "W", "month": "ME", "quarter": "QE"}
_FREQ_UNIT = {"D": "day", "W": "week", "ME": "month", "QE": "quarter"}
# ponytail: 20 records per period is a rule of thumb for proportions; confirm the number with the clinical owner.
_MIN_RECORDS_PER_PERIOD = 20


def _freq_for_proportion(df: pd.DataFrame, date_col: str, granularity: str | None) -> str | None:
    """Finest period, no finer than the design's, whose typical (non-empty) period holds enough records."""
    start = _FREQ_BY_GRANULARITY.get(str(granularity or "").lower())
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if start is None or dates.empty:
        return None
    order = list(_FREQ_UNIT)
    for freq in order[order.index(start):]:
        counts = pd.Series(1, index=dates).resample(freq).sum()
        if counts[counts > 0].median() >= _MIN_RECORDS_PER_PERIOD:
            return freq
    return order[-1]


def _bind_time_chart(
    design: ProjectDesign,
    profile: dict[str, Any],
    df: pd.DataFrame,
    value_key: str,
) -> tuple[dict[str, Any], dict[str, Confidence]]:
    params: dict[str, Any] = {}
    conf: dict[str, Confidence] = {}

    date_col = (
        design.time_structure.date_column
        if _column_exists(df, design.time_structure.date_column)
        else _first_role(profile, "date")
    )
    if _column_exists(df, date_col):
        params["date_col"] = date_col
        conf["date_col"] = (
            _field_confidence(design, "time_structure.date_column", bound=True)
            if date_col == design.time_structure.date_column
            else "low"
        )

    value = (
        design.primary_outcome.column
        if design.primary_outcome and _column_exists(df, design.primary_outcome.column)
        else _first_role(profile, "outcome", "numerator")
    )
    if _column_exists(df, value):
        params[value_key] = value
        conf[value_key] = (
            _field_confidence(design, "primary_outcome.column", bound=True)
            if design.primary_outcome and value == design.primary_outcome.column
            else "low"
        )

    denom = None
    if design.primary_outcome and design.primary_outcome.denominator_column:
        denom = design.primary_outcome.denominator_column
    binary = bool(design.primary_outcome) and design.primary_outcome.kind in ("proportion", "binary")
    if not _column_exists(df, denom) and not binary:
        denom = _first_role(profile, "denominator")
    if value_key in ("numerator_col", "count_col") and _column_exists(df, denom):
        params["denominator_col"] = denom
        conf["denominator_col"] = (
            _field_confidence(design, "primary_outcome.denominator_column", bound=True)
            if design.primary_outcome and denom == design.primary_outcome.denominator_column
            else "low"
        )

    if design.intervention.present and design.intervention.start_date:
        params["intervention_date"] = design.intervention.start_date

    if binary and "date_col" in params:
        freq = _freq_for_proportion(df, params["date_col"], design.time_structure.granularity)
        if freq:
            params["freq"] = freq
            conf["freq"] = "medium"

    return params, conf


_BINDERS = {
    "descriptive_summary": _bind_descriptive,
    "before_after_mean": _bind_before_after_mean,
    "before_after_pct": _bind_before_after_pct,
    "before_after_paired": _bind_before_after_paired,
    "run_chart": lambda d, p, df: _bind_time_chart(d, p, df, "value_col"),
    "p_chart": lambda d, p, df: _bind_time_chart(d, p, df, "numerator_col"),
    "u_c_chart": lambda d, p, df: _bind_time_chart(d, p, df, "count_col"),
}


def _feasible_templates(profile: dict[str, Any], df: pd.DataFrame) -> set[str]:
    """Mirror of analyze.determine_feasible_templates without importing that router."""
    roles = profile.get("candidate_roles", {})
    num_cols = [c["name"] for c in profile.get("columns", []) if c.get("inferred_type") == "Number"]
    date_cols = roles.get("date", [])
    grp_cols = roles.get("grouping", [])
    bin_cols = roles.get("binary", [])
    den_cols = roles.get("denominator", [])
    num_cand = roles.get("numerator", [])
    pairing_cols = roles.get("pairing_id", [])

    feasible: set[str] = set()
    if num_cols:
        feasible.add("descriptive_summary")
    if num_cols and grp_cols:
        feasible.add("before_after_mean")
    if (bin_cols or [c["name"] for c in profile.get("columns", []) if c.get("inferred_type") == "Category"]) and grp_cols:
        feasible.add("before_after_pct")
    if num_cols and grp_cols and pairing_cols:
        feasible.add("before_after_paired")
    if date_cols and (num_cols or bin_cols):
        feasible.add("run_chart")
    if date_cols and (bin_cols or (num_cand and den_cols)):
        feasible.add("p_chart")
    if date_cols and num_cols:
        feasible.add("u_c_chart")
    return feasible


def _with_inferred_kind(design: ProjectDesign, profile: dict[str, Any]) -> ProjectDesign:
    """The manual design form has no outcome kind; a Yes/No outcome column is a binary outcome."""
    outcome = design.primary_outcome
    if not outcome or outcome.kind not in (None, "unknown"):
        return design
    types = {c.get("name"): c.get("inferred_type") for c in profile.get("columns", [])}
    if types.get(outcome.column) != "Yes/No":
        return design
    return design.model_copy(update={"primary_outcome": outcome.model_copy(update={"kind": "binary"})})


def propose_analyses(
    design: ProjectDesign,
    profile: dict[str, Any],
    df: pd.DataFrame | None = None,
) -> list[AnalysisPlanItem]:
    """Draft analysis plan items from design + profile. Never marks the plan confirmed."""
    frame = df if df is not None else pd.DataFrame()
    design = _with_inferred_kind(design, profile)
    feasible = _feasible_templates(profile, frame) if profile else set()
    # When profile has no candidate roles yet, do not hard-filter; still propose from design.
    apply_feasibility = bool(feasible)

    items: list[AnalysisPlanItem] = []
    for idx, template in enumerate(_templates_for_design(design)):
        if apply_feasibility and template not in feasible:
            continue
        binder = _BINDERS.get(template)
        if not binder:
            continue
        parameters, param_confidence = binder(design, profile, frame)
        display_name, question, rationale = _DISPLAY.get(template, (template, "", ""))
        needs_clarification = (not parameters) or any(c == "low" for c in param_confidence.values())
        limitations: list[str] = []
        kind = design.primary_outcome.kind if design.primary_outcome else "unknown"
        if "denominator_col" not in parameters and ((template == "p_chart" and kind not in ("proportion", "binary")) or (template == "u_c_chart" and kind == "rate")):
            limitations.append(
                "No denominator column is assigned (for example patient days). "
                "Assign one in the Data Review role table or in the project definition. "
                + (
                    "Without a denominator this runs as a counts-only C chart, which assumes the same exposure every period."
                    if template == "u_c_chart"
                    else "Without a denominator each record is counted as one case in its period."
                )
            )
            needs_clarification = True
        chosen = parameters.get("freq")
        wanted = _FREQ_BY_GRANULARITY.get(str(design.time_structure.granularity or "").lower())
        if chosen and wanted and chosen != wanted:
            limitations.append(
                f"Records were grouped by {_FREQ_UNIT[chosen]} instead of {_FREQ_UNIT[wanted]}, "
                f"the finest period with at least {_MIN_RECORDS_PER_PERIOD} records in a typical period."
            )
        den_roles = (profile.get("candidate_roles") or {}).get("denominator") or []
        if len(den_roles) > 1 and "denominator_col" in parameters:
            count = "Two columns are" if len(den_roles) == 2 else f"{len(den_roles)} columns are"
            limitations.append(
                f"{count} set as Denominator. This analysis will use {parameters['denominator_col']}. "
                "Change the other one in the Data Review role table if that is wrong."
            )
            needs_clarification = True
        items.append(
            AnalysisPlanItem(
                id=f"{template}-{idx + 1}",
                template=template,
                display_name=display_name,
                question=question,
                rationale=rationale,
                parameters=parameters,
                param_confidence=param_confidence,
                assumptions=[],
                limitations=limitations,
                needs_clarification=needs_clarification,
            )
        )
    return items
