"""Apply agreed handoff steps to an upload and re-derive quality flags / profile from the result."""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.cleaning_steps import StepError, apply_steps
from api.upload_utils import _load_raw


class StepsApplyError(HTTPException):
    """Agreed changes cannot be applied to the data. Surfaces as a 409."""

    def __init__(self, message: str):
        super().__init__(
            status_code=409,
            detail={
                "message": "The agreed data changes could not be applied to your file, so nothing was analysed. "
                f"{message} Please review the changes in the handoff document.",
                "required_phase": "data",
            },
        )


def _stored_steps(upload) -> list[dict]:
    raw = getattr(upload, "handoff_steps", None)
    if raw in (None, "", "[]"):
        return []
    try:
        steps = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise StepsApplyError("The stored changes are not readable.") from exc
    if not isinstance(steps, list):
        raise StepsApplyError("The stored changes are not a list.")
    return steps


def _clean(upload):
    df, restored = _load_raw(upload)
    steps = _stored_steps(upload)
    if not steps:
        return df, [], restored
    try:
        cleaned, report = apply_steps(df, steps)
    except StepError as exc:
        where = f"Change {exc.index + 1}: " if exc.index is not None else ""
        raise StepsApplyError(f"{where}{exc.message}.") from exc
    return cleaned, report, restored


def load_cleaned_dataframe(upload, with_report: bool = False):
    """Raw upload with stored handoff steps applied. Returns (df, report) when with_report."""
    df, report, _ = _clean(upload)
    return (df, report) if with_report else df


def _col_types(upload) -> dict[str, str]:
    try:
        parsed = json.loads(upload.col_types or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def recheck_flags(upload) -> list[dict[str, Any]]:
    """Run the data-quality rules on the cleaned frame; returns new flag dicts (with ids)."""
    from api.routers.upload import run_data_quality  # lazy: the router imports upload_utils

    df, _, restored = _clean(upload)
    col_types = {c: t for c, t in _col_types(upload).items() if c in df.columns}
    # Columns added/renamed by steps have no stored type; fall back to the upload-time detector.
    from api.routers.upload import detect_col_type

    for c in df.columns:
        col_types.setdefault(c, detect_col_type(c, df[c]))
    return run_data_quality(df, col_types, restored)


def rebuild_profile(upload, db: Session) -> dict[str, Any]:
    """Refresh the cached dataset_profile from the cleaned frame. Caller commits."""
    from api.dataset_profile import build_profile

    df = load_cleaned_dataframe(upload)
    col_types = {c: t for c, t in _col_types(upload).items() if c in df.columns}
    profile = build_profile(df, col_types, getattr(upload, "dictionary_text", None))
    upload.dataset_profile = json.dumps(profile)
    db.add(upload)
    return profile
