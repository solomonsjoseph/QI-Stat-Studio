"""Deterministic handoff document (Markdown). Pure functions, no DB, no AI.

The fenced ```handoff-steps block is the source of truth for applied cleaning steps.
Everything else is human-readable text that can be edited without changing the steps.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.cleaning_steps import describe_step, validate_steps
from api.flag_ids import with_ids

MAX_EXAMPLES = 10
MAX_EXAMPLE_LEN = 80
FENCE = "handoff-steps"
LIST_START = "<!-- agreed-changes:start -->"
LIST_END = "<!-- agreed-changes:end -->"
_BLOCK_RE = re.compile(r"^```" + FENCE + r"[ \t]*\n(.*?)\n```[ \t]*$", re.S | re.M)
_LIST_RE = re.compile(re.escape(LIST_START) + r".*?" + re.escape(LIST_END), re.S)


def _line(x: Any) -> str:
    """Single-line text so no value can start a line (and so open a fence)."""
    return " ".join(str(x).split())


def _cell(x: Any) -> str:
    return _line(x).replace("|", "\\|")


def _examples(values: Any) -> List[str]:
    out: List[str] = []
    for v in values or []:
        s = _line(v)
        if len(s) > MAX_EXAMPLE_LEN:
            s = s[: MAX_EXAMPLE_LEN - 3] + "..."
        if s not in out:
            out.append(s)
        if len(out) == MAX_EXAMPLES:
            break
    return out


def _actor(x: Any) -> str:
    """Only these labels reach the document, so no email or name can leak into handoff_md."""
    return x if x in ("user", "advisor", "system") else "user"


def _steps_json(steps: List[dict]) -> str:
    return json.dumps(steps, ensure_ascii=False, indent=2)


def _changes_region(steps: List[dict]) -> str:
    if steps:
        items = []
        for i, s in enumerate(steps, 1):
            ids = s.get("warning_ids") or []
            tail = f" (warnings: {', '.join(_line(w) for w in ids)})" if ids else ""
            note = f" Note: {_line(s['note'])}" if s.get("note") else ""
            items.append(f"{i}. {_line(describe_step(s))}{tail}{note}")
        body = "\n".join(items)
    else:
        body = "No changes agreed."
    return f"{LIST_START}\n{body}\n{LIST_END}"


def _steps_block(steps: List[dict]) -> str:
    return f"```{FENCE}\n{_steps_json(steps)}\n```"


def revisions_to_markdown(revisions: Optional[List[dict]]) -> str:
    if not revisions:
        return "No changes recorded."
    lines = []
    for r in revisions:
        rev = f"r{r['revision']} " if r.get("revision") is not None else ""
        ids = r.get("warning_ids") or []
        w = f" Warnings: {', '.join(_line(i) for i in ids)}." if ids else ""
        lines.append(
            f"- {rev}{_line(r.get('created_at', ''))} {_actor(r.get('actor'))} "
            f"[{_line(r.get('kind', ''))}]: {_line(r.get('summary', ''))} "
            f"(steps {r.get('steps_before_count', 0)} to {r.get('steps_after_count', 0)}).{w}"
        )
    return "\n".join(lines)


def new_revision_entry(kind: str, summary: str, steps_before: List[dict], steps_after: List[dict],
                       warning_ids: Optional[List[str]], actor: str,
                       revision: Optional[int] = None, created_at: Optional[str] = None) -> Dict[str, Any]:
    """Change-log entry. Caller sets `revision` (number) and may pin `created_at` for tests."""
    return {
        "revision": revision,
        "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": _actor(actor),
        "kind": kind,
        "summary": summary,
        "warning_ids": list(warning_ids or []),
        "steps_before_count": len(steps_before),
        "steps_after_count": len(steps_after),
        "steps_snapshot": json.loads(json.dumps(steps_after)),
    }


def build_handoff_md(*, project_name: str, filename: str, dictionary_text: Optional[str],
                     profile: dict, flags: List[dict], col_types: Dict[str, str],
                     steps: List[dict], revisions: Optional[List[dict]],
                     examples: Optional[Dict[str, List[Any]]] = None) -> str:
    validate_steps(steps)
    examples = examples or {}
    flags = with_ids(flags)
    roles = profile.get("candidate_roles") or {}
    out = [
        f"# Handoff: {_line(project_name)}", "",
        "## Dataset overview", "",
        f"- File: {_line(filename)}",
        f"- Rows: {profile.get('row_count', 0)}",
        f"- Columns: {profile.get('column_count', 0)}",
        f"- Duplicate rows: {profile.get('duplicate_row_count', 0)}",
    ]
    for role, cols in roles.items():
        if cols:
            out.append(f"- Candidate {role}: {', '.join(_line(c) for c in cols)}")
    out += ["", "## Data dictionary", ""]
    if dictionary_text and dictionary_text.strip():
        out += [("> " + l).rstrip() for l in dictionary_text.strip().splitlines()]
    else:
        out.append("No data dictionary provided.")
    out += ["", "## Columns", "", "| Column | Type | Role | Missing % |", "| --- | --- | --- | --- |"]
    for c in profile.get("columns", []):
        name = c["name"]
        typ = col_types.get(name, c.get("inferred_type", ""))
        role = ", ".join(c.get("roles") or []) or "unknown"
        out.append(f"| {_cell(name)} | {_cell(typ)} | {_cell(role)} | {c.get('missing_pct', 0)} |")
    out += ["", "## Quality warnings", ""]
    if not flags:
        out.append("No warnings.")
    for f in flags:
        out.append(f"- `{_line(f['id'])}` [{_line(f.get('severity', ''))}] {_line(f.get('msg', ''))}")
        for label, key in (("Why", "why"), ("Suggestion", "suggestion")):
            if f.get(key):
                out.append(f"  - {label}: {_line(f[key])}")
        ex = _examples(examples.get(f["id"]))
        if ex:
            out.append(f"  - Examples: {'; '.join(ex)}")
    out += ["", "## Agreed changes", "", _changes_region(steps),
            "", "## Change log", "", revisions_to_markdown(revisions),
            "", "## Machine-readable steps", "",
            "This block is the source of truth for applied changes.", "",
            _steps_block(steps), ""]
    return "\n".join(out)


def extract_steps(md: str) -> List[dict]:
    found = _BLOCK_RE.findall(md or "")
    if not found:
        raise ValueError(f"handoff has no ```{FENCE} block (missing or not closed)")
    if len(found) > 1:
        raise ValueError(f"handoff has {len(found)} ```{FENCE} blocks, expected exactly one")
    try:
        steps = json.loads(found[0])
    except json.JSONDecodeError as e:
        raise ValueError(f"```{FENCE} block is not valid JSON: {e}") from None
    validate_steps(steps)  # StepError is a ValueError
    return steps


def replace_steps(md: str, steps: List[dict]) -> str:
    extract_steps(md)  # fail loudly on a malformed block
    validate_steps(steps)
    if len(_LIST_RE.findall(md)) != 1:
        raise ValueError("handoff agreed-changes markers are missing or duplicated")
    # lambdas so backslashes in the text are not read as regex escapes
    md = _LIST_RE.sub(lambda _m: _changes_region(steps), md)
    return _BLOCK_RE.sub(lambda _m: _steps_block(steps), md)
