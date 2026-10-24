"""Data changes applied to an upload, as plain dicts for exports (report and R/SAS/SPSS scripts).

Snapshot shape (stored under result_json["data_changes"]):
  {"steps": [{"op", "description", "rows_before", "rows_after", "rows_removed", "cells_changed",
              "warnings": [message, ...], "note"}],
   "decisions": [text, ...]}   # agreements recorded without a data change
Returns None when there is nothing to list.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

MAX_LINE = 400


def one_line(x: Any) -> str:
    """Single line of text: every newline or odd whitespace run becomes one space."""
    s = " ".join(str(x).split())
    return s if len(s) <= MAX_LINE else s[: MAX_LINE - 3] + "..."


def _loads(raw: Any, fallback: Any) -> Any:
    try:
        v = json.loads(raw) if isinstance(raw, str) and raw else fallback
    except (TypeError, ValueError):
        return fallback
    return v if isinstance(v, type(fallback)) else fallback


def build_data_changes(upload: Any) -> Optional[Dict[str, Any]]:
    from api.cleaning_runtime import load_cleaned_dataframe

    if upload is None:
        return None
    msgs = {f.get("id"): f.get("msg") or f.get("message") or f.get("id")
            for f in _loads(upload.quality_flags, []) if isinstance(f, dict)}
    steps: List[dict] = []
    if _loads(getattr(upload, "handoff_steps", None), []):
        _, report = load_cleaned_dataframe(upload, with_report=True)
        for r in report:
            steps.append({
                "op": r.get("op", ""),
                "description": r["description"],
                "rows_before": r["rows_before"],
                "rows_after": r["rows_after"],
                "rows_removed": r["rows_before"] - r["rows_after"],
                "cells_changed": r["cells_changed"],
                "warnings": [msgs.get(w, w) for w in r.get("warning_ids", [])],
                "note": r.get("note", ""),
            })
    # Change-log entries that left the steps unchanged are agreements recorded as notes only.
    decisions = [
        r["summary"] for r in _loads(getattr(upload, "handoff_revisions", None), [])
        if isinstance(r, dict) and r.get("kind") == "apply" and r.get("summary")
        and r.get("steps_before_count") == r.get("steps_after_count")
    ]
    return {"steps": steps, "decisions": decisions} if steps or decisions else None


def step_line(s: dict) -> str:
    """One-line text for a snapshot step, used by the report and the script comments."""
    if s.get("op") == "set_role":
        out = f"{s['description']} No rows changed."
        if s.get("warnings"):
            out += " Warnings: " + "; ".join(s["warnings"]) + "."
        if s.get("note"):
            out += f" Note: {s['note']}"
        return one_line(out)
    out = (f"{s['description']} Rows before {s['rows_before']}, after {s['rows_after']}, "
           f"removed {s['rows_removed']}, cells changed {s['cells_changed']}.")
    if s.get("warnings"):
        out += " Warnings: " + "; ".join(s["warnings"]) + "."
    if s.get("note"):
        out += f" Note: {s['note']}"
    return one_line(out)


def data_change_lines(dc: Optional[dict]) -> List[str]:
    if not dc:
        return []
    return [step_line(s) for s in dc.get("steps", [])] + [one_line(f"Decision: {d}") for d in dc.get("decisions", [])]


def comment_block(lines: List[str], language: str) -> str:
    """Comment header for a generated script. Text is single-line and cannot close the comment."""
    if not lines:
        return ""
    head = "Data changes applied before this analysis (rows are counts at each step):"
    if language == "r":
        mk = lambda t: "# " + t
    elif language == "spss":
        # SPSS comments end at a period at the end of a line; the text is one line and ends with one
        mk = lambda t: "* " + t.rstrip(".") + "."
    else:
        mk = lambda t: "/* " + t.replace("*/", "* /").replace("/*", "/ *") + " */"
    return "\n".join(mk(one_line(t)) for t in [head, *lines]) + "\n\n"
