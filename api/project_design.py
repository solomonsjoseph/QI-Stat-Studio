from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from api.models_api import FieldStatus, ProjectDesign

DESIGN_FIELDS = [
    "aim",
    "population",
    "setting",
    "intervention.present",
    "intervention.description",
    "intervention.start_date",
    "primary_outcome.label",
    "primary_outcome.column",
    "primary_outcome.kind",
    "primary_outcome.denominator_column",
    "comparison",
    "time_structure.has_dates",
    "time_structure.date_column",
    "time_structure.granularity",
    "unit_of_analysis",
    "group_column",
    "pre_label",
    "post_label",
    "paired",
    "pairing_id_column",
    "design_type",
]


def get_field_value(data: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    curr: Any = data
    for p in parts:
        if not isinstance(curr, dict):
            return None
        curr = curr.get(p)
    return curr


def set_field_value(data: dict[str, Any], path: str, val: Any) -> None:
    parts = path.split(".")
    curr = data
    for p in parts[:-1]:
        if p not in curr or not isinstance(curr[p], dict):
            curr[p] = {}
        curr = curr[p]
    curr[parts[-1]] = val


def validate_design_columns(design: ProjectDesign, col_types: dict[str, Any]) -> dict[str, list[str]]:
    """Validate that every named column exists in the dataset's col_types.

    Returns a field_errors dictionary.
    """
    field_errors: dict[str, list[str]] = {}
    valid_cols = set(col_types.keys())

    def check(col_name: str | None, field_key: str):
        if col_name and col_name not in valid_cols:
            field_errors.setdefault(field_key, []).append(
                f"Column '{col_name}' does not exist in the uploaded dataset."
            )

    if design.primary_outcome:
        check(design.primary_outcome.column, "primary_outcome.column")
        check(design.primary_outcome.denominator_column, "primary_outcome.denominator_column")

    if design.time_structure:
        check(design.time_structure.date_column, "time_structure.date_column")

    check(design.group_column, "group_column")
    check(design.pairing_id_column, "pairing_id_column")

    for idx, sec in enumerate(design.secondary_outcomes):
        check(sec.column, f"secondary_outcomes[{idx}].column")
        check(sec.denominator_column, f"secondary_outcomes[{idx}].denominator_column")

    return field_errors


def merge_user_design(new_design: ProjectDesign, old_design_dict: dict[str, Any]) -> ProjectDesign:
    """Apply provenance rules for a user-submitted design edit."""
    new_data = new_design.model_dump()
    old_status = old_design_dict.get("status", {}) if isinstance(old_design_dict, dict) else {}
    status_map: dict[str, FieldStatus] = {}

    for path in DESIGN_FIELDS:
        new_val = get_field_value(new_data, path)
        old_val = get_field_value(old_design_dict, path)
        prior_st = old_status.get(path)

        if new_val in (None, "", False, {}):
            status_map[path] = "unknown"
        elif old_val is not None and new_val != old_val:
            status_map[path] = "user-corrected"
        elif prior_st in ("user-confirmed", "user-corrected"):
            status_map[path] = prior_st
        else:
            status_map[path] = "user-confirmed"

    new_design.status = status_map
    return new_design


def merge_ai_design(ai_design: ProjectDesign, old_design_dict: dict[str, Any]) -> ProjectDesign:
    """Apply provenance rules for an AI clarify turn.

    All AI-produced fields are marked 'inferred'. Any previously stored
    'user-confirmed' or 'user-corrected' status AND value is restored so
    a later AI turn cannot overwrite or downgrade a user decision.
    """
    ai_data = ai_design.model_dump()
    old_status = old_design_dict.get("status", {}) if isinstance(old_design_dict, dict) else {}
    status_map: dict[str, FieldStatus] = {}

    for path in DESIGN_FIELDS:
        prior_st = old_status.get(path)
        if prior_st in ("user-confirmed", "user-corrected"):
            # Restore user decision and status
            old_val = get_field_value(old_design_dict, path)
            set_field_value(ai_data, path, old_val)
            status_map[path] = prior_st
        else:
            val = get_field_value(ai_data, path)
            if val not in (None, "", False, {}):
                status_map[path] = "inferred"
            else:
                status_map[path] = "unknown"

    ai_data["status"] = status_map
    return ProjectDesign.model_validate(ai_data)
