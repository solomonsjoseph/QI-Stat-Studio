"""Structured data-cleaning steps. Pure pandas, no DB, no eval.

A step is a JSON-serialisable dict: {"op": ..., <args>, "warning_ids": [...], "note": "..."}.
apply_steps never mutates its input and is all-or-nothing: any StepError aborts the call.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


class StepError(ValueError):
    def __init__(self, index: int | None, message: str):
        self.index = index
        self.message = message
        super().__init__(f"step {index}: {message}" if index is not None else message)


MAX_STEPS, MAX_ENTRIES, MAX_TEXT = 100, 1000, 500
COMMON_KEYS = {"op", "warning_ids", "note"}
# op -> (required args, optional args)
OPS: dict[str, tuple[set[str], set[str]]] = {
    "recode": ({"column", "mapping"}, set()),
    "merge_values": ({"column", "values", "into"}, set()),
    "trim": ({"columns"}, set()),
    "change_case": ({"columns", "mode"}, set()),
    "retype": ({"column", "to"}, {"errors", "format"}),
    "rename_column": ({"column", "new_name"}, set()),
    "set_value": ({"column", "value"}, {"where"}),
    "drop_duplicates": (set(), {"subset", "keep"}),
    "drop_rows": ({"where"}, set()),
    "drop_column": ({"column"}, set()),
    "set_role": ({"column", "role"}, set()),
}
ROLES = {"outcome", "numerator", "denominator", "grouping", "identifier", "pairing_id", "none"}
CONDITION_OPS = {"eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "isnull", "notnull", "contains"}
CASE_MODES = {"lower", "upper", "title", "capitalize"}
RETYPE_TARGETS = {"numeric", "date", "string", "category"}

STEP_VOCABULARY = """\
Each step is a JSON object with "op", the op's arguments, and optional "warning_ids" (list) and "note" (string).
Ops:
- recode: column, mapping {old: new}. Replaces listed values; all mappings use the original values.
- merge_values: column, values [..], into. Many values become one.
- trim: columns [..]. Strips leading/trailing whitespace from text.
- change_case: columns [..], mode (lower|upper|title|capitalize).
- retype: column, to (numeric|date|string|category), errors (raise|coerce, default raise), format (date only, optional strptime format).
- rename_column: column, new_name.
- set_value: column, value, where (optional condition; omitted means every row). Use where isnull to fill missing values.
- drop_duplicates: subset [..] (optional, default all columns), keep (first|last, default first).
- drop_rows: where (condition). Removes matching rows.
- drop_column: column.
- set_role: column, role (outcome|numerator|denominator|grouping|identifier|pairing_id|none). Only when the resident asks to use a column in that role (for example "use patient_days as the denominator"); none clears the role. It changes no data, only how the column is used in the analysis.
Condition: {"column": c, "op": eq|ne|lt|le|gt|ge|in|not_in|isnull|notnull|contains, "value": v}
  (value is omitted for isnull/notnull, a list for in/not_in, text for contains),
  or {"all": [conditions]} / {"any": [conditions]}.
Matching: text and numbers match loosely ("1" matches 1 and 1.0). ne and not_in never match missing values
(SQL semantics), so use "any" with isnull to include them. Row numbers are renumbered from 0 after the steps run.
Limits: at most 100 steps, 1000 entries in any list or mapping, 500 characters in any text value.
Nothing outside this list is allowed. Never emit code.
"""


# ---------- validation ----------

def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _check_condition(c: Any, idx: int) -> None:
    if not isinstance(c, dict):
        raise StepError(idx, "condition must be an object")
    if "all" in c or "any" in c:
        key = "all" if "all" in c else "any"
        if set(c) != {key} or not isinstance(c[key], list) or not c[key]:
            raise StepError(idx, f'"{key}" must be the only key and a non-empty list of conditions')
        for sub in c[key]:
            _check_condition(sub, idx)
        return
    extra = set(c) - {"column", "op", "value"}
    if extra or not isinstance(c.get("column"), str) or c.get("op") not in CONDITION_OPS:
        raise StepError(idx, f"bad condition {c!r}; needs column and op in {sorted(CONDITION_OPS)}")
    op = c["op"]
    if op in ("isnull", "notnull"):
        if "value" in c:
            raise StepError(idx, f"condition op {op} takes no value")
        return
    if "value" not in c:
        raise StepError(idx, f"condition op {op} needs a value")
    v = c["value"]
    if op in ("in", "not_in"):
        if not isinstance(v, list) or not all(_scalar(x) for x in v):
            raise StepError(idx, f"condition op {op} needs a list of values")
    elif op == "contains":
        if not isinstance(v, str):
            raise StepError(idx, "condition op contains needs a text value")
    elif not _scalar(v) or (op in ("lt", "le", "gt", "ge") and v is None):
        raise StepError(idx, f"condition op {op} needs a single value")


def _cols(c: Any) -> list[str]:
    if "all" in c or "any" in c:
        return [x for s in c.get("all", c.get("any")) for x in _cols(s)]
    return [c["column"]]


def _check_step(s: Any, i: int) -> None:
    if not isinstance(s, dict):
        raise StepError(i, "step must be an object")
    op = s.get("op")
    if op not in OPS:
        raise StepError(i, f"unknown op {op!r}; allowed: {sorted(OPS)}")
    req, opt = OPS[op]
    missing = req - set(s)
    extra = set(s) - req - opt - COMMON_KEYS
    if missing:
        raise StepError(i, f"op {op} is missing {sorted(missing)}")
    if extra:
        raise StepError(i, f"op {op} has unexpected keys {sorted(extra)}")
    w = s.get("warning_ids", [])
    if not isinstance(w, list) or not all(isinstance(x, str) for x in w):
        raise StepError(i, "warning_ids must be a list of strings")
    if not isinstance(s.get("note", ""), str):
        raise StepError(i, "note must be a string")
    for k in ("column", "new_name", "into"):
        if k in s and not isinstance(s[k], str) and not (k == "into" and _scalar(s[k])):
            raise StepError(i, f"{k} must be text")
    for k in ("columns", "subset", "values"):
        if k in s and (not isinstance(s[k], list) or not s[k]
                       or (k != "values" and not all(isinstance(x, str) for x in s[k]))):
            raise StepError(i, f"{k} must be a non-empty list" + (" of column names" if k != "values" else ""))
    if op == "recode" and (not isinstance(s["mapping"], dict) or not s["mapping"]
                           or not all(_scalar(v) for v in s["mapping"].values())):
        raise StepError(i, "mapping must be a non-empty object of old value to new value")
    if op == "change_case" and s["mode"] not in CASE_MODES:
        raise StepError(i, f"mode must be one of {sorted(CASE_MODES)}")
    if op == "retype":
        if s["to"] not in RETYPE_TARGETS:
            raise StepError(i, f"to must be one of {sorted(RETYPE_TARGETS)}")
        if s.get("errors", "raise") not in ("raise", "coerce"):
            raise StepError(i, "errors must be raise or coerce")
        if "format" in s and (s["to"] != "date" or not isinstance(s["format"], str)):
            raise StepError(i, "format is a text option for to=date only")
    if op == "set_value" and not _scalar(s["value"]):
        raise StepError(i, "value must be a single value")
    if op == "merge_values" and not all(_scalar(v) for v in s["values"]):
        raise StepError(i, "values must be single values")
    if op == "set_role" and s["role"] not in ROLES:
        raise StepError(i, f"role must be one of {sorted(ROLES)}")
    if op == "drop_duplicates" and s.get("keep", "first") not in ("first", "last"):
        raise StepError(i, "keep must be first or last")
    if "where" in s:
        _check_condition(s["where"], i)


def _check_size(x: Any, i: int) -> None:
    if isinstance(x, str):
        if len(x) > MAX_TEXT:
            raise StepError(i, f"text values are limited to {MAX_TEXT} characters")
    elif isinstance(x, (list, dict)):
        if len(x) > MAX_ENTRIES:
            raise StepError(i, f"lists and mappings are limited to {MAX_ENTRIES} entries")
        for k, v in (x.items() if isinstance(x, dict) else enumerate(x)):
            if isinstance(k, str):
                _check_size(k, i)
            _check_size(v, i)


def validate_steps(steps: Any) -> None:
    """Shape check without a dataframe. Raises StepError."""
    if not isinstance(steps, list):
        raise StepError(None, "steps must be a list")
    if len(steps) > MAX_STEPS:
        raise StepError(None, f"at most {MAX_STEPS} steps are allowed")
    for i, s in enumerate(steps):
        _check_step(s, i)
        _check_size({k: v for k, v in s.items() if k != "note"}, i)


# ---------- description ----------

def _cond_text(c: dict) -> str:
    if "all" in c or "any" in c:
        key = "all" if "all" in c else "any"
        return "(" + (" and " if key == "all" else " or ").join(_cond_text(x) for x in c[key]) + ")"
    words = {"eq": "equals", "ne": "is not", "lt": "is less than", "le": "is at most",
             "gt": "is greater than", "ge": "is at least", "in": "is one of", "not_in": "is not one of",
             "contains": "contains", "isnull": "is missing", "notnull": "is not missing"}
    base = f"{c['column']} {words[c['op']]}"
    if c["op"] in ("isnull", "notnull"):
        return base
    text = f"{base} {c['value']!r}"
    return f"{text} (missing values are kept)" if c["op"] in ("ne", "not_in") else text


def describe_step(step: dict) -> str:
    op = step["op"]
    col = step.get("column")
    if op == "recode":
        pairs = ", ".join(f"{k!r} to {v!r}" for k, v in step["mapping"].items())
        return f"Recoded values in {col}: {pairs}."
    if op == "merge_values":
        return f"Merged values {step['values']!r} in {col} into {step['into']!r}."
    if op == "trim":
        return f"Trimmed leading and trailing whitespace in {', '.join(step['columns'])}."
    if op == "change_case":
        return f"Changed text in {', '.join(step['columns'])} to {step['mode']} case."
    if op == "retype":
        extra = ", values that cannot be converted become missing" if step.get("errors") == "coerce" else ""
        return f"Converted {col} to {step['to']}{extra}."
    if op == "rename_column":
        return f"Renamed column {col} to {step['new_name']}."
    if op == "set_value":
        where = f" where {_cond_text(step['where'])}" if "where" in step else " in every row"
        return f"Set {col} to {step['value']!r}{where}."
    if op == "drop_duplicates":
        on = ", ".join(step["subset"]) if step.get("subset") else "all columns"
        return f"Removed duplicate rows (compared on {on}, kept the {step.get('keep', 'first')})."
    if op == "drop_rows":
        return f"Removed rows where {_cond_text(step['where'])}."
    if op == "drop_column":
        return f"Removed column {col}."
    if op == "set_role":
        if step["role"] == "none":
            return f"Clear the role of column {col}."
        return f"Set the role of column {col} to {step['role']}."
    return f"Unknown step {op}."


def _affected(step: dict) -> list[str]:
    op = step["op"]
    if "columns" in step:
        return list(step["columns"])
    if op == "drop_rows":
        return list(dict.fromkeys(_cols(step["where"])))
    if op == "drop_duplicates":
        return list(step.get("subset") or [])
    if op == "set_value" and "where" in step:
        return list(dict.fromkeys([step["column"], *_cols(step["where"])]))
    return [step["column"]] if "column" in step else []


# ---------- evaluation ----------

def _need(df: pd.DataFrame, cols: list[str], i: int) -> None:
    for c in cols:
        if c not in df.columns:
            raise StepError(i, f"unknown column {c!r}; available: {list(df.columns)}")


def _as_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _loose_eq(s: pd.Series, v: Any) -> pd.Series:
    """Equality that also matches "1" against numeric 1 or 1.0 (both ways). Missing never equals."""
    if v is None:
        return s.isna()
    vnum = _as_number(v)

    def eq(x: Any) -> bool:
        if _isna(x):
            return False
        if x == v or str(x) == str(v):
            return True
        if vnum is not None and not isinstance(x, (bool, str)):
            xn = _as_number(x)
            return xn is not None and xn == vnum
        return False

    return s.astype(object).map(eq).astype(bool)


def _isna(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NaT or x is pd.NA


def _mask(df: pd.DataFrame, c: dict, i: int) -> pd.Series:
    if "all" in c or "any" in c:
        key = "all" if "all" in c else "any"
        masks = [_mask(df, x, i) for x in c[key]]
        out = masks[0]
        for m in masks[1:]:
            out = (out & m) if key == "all" else (out | m)
        return out
    _need(df, [c["column"]], i)
    s, op, v = df[c["column"]], c["op"], c.get("value")
    try:
        if op == "isnull":
            return s.isna()
        if op == "notnull":
            return s.notna()
        if op == "eq":
            return _loose_eq(s, v)
        if op == "ne":
            return ~_loose_eq(s, v) & s.notna()
        if op == "in":
            return pd.concat([_loose_eq(s, x) for x in v], axis=1).any(axis=1) if v else pd.Series(False, index=s.index)
        if op == "not_in":
            return (~(pd.concat([_loose_eq(s, x) for x in v], axis=1).any(axis=1)) if v else pd.Series(True, index=s.index)) & s.notna()
        if op == "contains":
            return s.astype(object).map(lambda x: isinstance(x, str) and v in x).astype(bool)
        cmp = {"lt": s.lt, "le": s.le, "gt": s.gt, "ge": s.ge}[op]
        return cmp(v).fillna(False).astype(bool)
    except (TypeError, ValueError):
        # no pandas text here: it can quote cell values
        raise StepError(i, f"cannot compare column {c['column']!r} using {op}; the column holds values of mixed or incompatible types") from None


def _retype(s: pd.Series, step: dict, i: int) -> pd.Series:
    to, errors = step["to"], step.get("errors", "raise")
    try:
        if to == "numeric":
            return pd.to_numeric(s, errors=errors)
        if to == "date":
            return pd.to_datetime(s, errors=errors, format=step.get("format"))
        if to == "string":
            return s.astype(object).map(lambda x: x if _isna(x) else str(x))
        return s.astype("category")
    except (ValueError, TypeError, OverflowError):
        # no pandas text here: it quotes the offending cell value
        bad = ""
        try:
            conv = pd.to_numeric(s, errors="coerce") if to == "numeric" else pd.to_datetime(s, errors="coerce", format=step.get("format"))
            n = int((conv.isna() & s.notna()).sum())
            bad = f"{n} value{'s' if n != 1 else ''} in " if n else "values in "
        except Exception:
            bad = "values in "
        what = "numbers" if to == "numeric" else "dates"
        raise StepError(i, f"{bad}column {step['column']!r} could not be converted to {what}; use errors=coerce or fix them") from None


def _text_map(s: pd.Series, fn) -> pd.Series:
    return s.astype(object).map(lambda x: fn(x) if isinstance(x, str) else x)


def _assign(s: pd.Series, mask: pd.Series, value: Any) -> pd.Series:
    out = s.astype(object)
    out[mask] = value
    return out.infer_objects()


def _changed(a: pd.Series, b: pd.Series) -> pd.Series:
    a, b = a.astype(object), b.astype(object)
    return a.ne(b) & ~(a.isna() & b.isna())


def _run(df: pd.DataFrame, step: dict, i: int) -> pd.DataFrame:
    op = step["op"]
    _need(df, [x for k in ("column",) if k in step for x in [step[k]]] + step.get("columns", []) + step.get("subset", []), i)
    if op == "recode":
        s = df[step["column"]]
        out = s.astype(object).copy()
        for old, new in step["mapping"].items():
            out[_loose_eq(s, old)] = new
        df[step["column"]] = out.infer_objects()
    elif op == "merge_values":
        s = df[step["column"]]
        m = pd.concat([_loose_eq(s, v) for v in step["values"]], axis=1).any(axis=1)
        df[step["column"]] = _assign(s, m, step["into"])
    elif op == "trim":
        for c in step["columns"]:
            df[c] = _text_map(df[c], str.strip)
    elif op == "change_case":
        fn = getattr(str, step["mode"])
        for c in step["columns"]:
            df[c] = _text_map(df[c], fn)
    elif op == "retype":
        df[step["column"]] = _retype(df[step["column"]], step, i)
    elif op == "rename_column":
        if step["new_name"] in df.columns and step["new_name"] != step["column"]:
            raise StepError(i, f"column {step['new_name']!r} already exists")
        df = df.rename(columns={step["column"]: step["new_name"]})
    elif op == "set_value":
        m = _mask(df, step["where"], i) if "where" in step else pd.Series(True, index=df.index)
        df[step["column"]] = _assign(df[step["column"]], m, step["value"])
    elif op == "drop_duplicates":
        df = df.drop_duplicates(subset=step.get("subset"), keep=step.get("keep", "first")).copy()
    elif op == "drop_rows":
        df = df[~_mask(df, step["where"], i)].copy()
    elif op == "drop_column":
        df = df.drop(columns=[step["column"]])
    return df


def apply_steps(df: pd.DataFrame, steps: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    """Return (cleaned copy with a fresh 0..n-1 index, one report entry per step). Input is never mutated."""
    validate_steps(steps)
    cur = df.copy(deep=True)  # the only full copy; _run mutates it step by step
    report: list[dict] = []
    for i, step in enumerate(steps):
        op = step["op"]
        row_op = op in ("drop_rows", "drop_duplicates")
        cols = [] if row_op or op in ("rename_column", "drop_column", "set_role") else (
            [step["column"]] if "column" in step else step["columns"])
        _need(cur, cols, i)
        before = {c: cur[c].copy() for c in cols}
        rows_before = len(cur)
        cur = _run(cur, step, i)
        rows_after = len(cur)
        if row_op:
            rows_changed, cells = rows_before - rows_after, 0
        elif not cols:
            rows_changed, cells = 0, 0
        else:
            diff = pd.DataFrame({c: _changed(before[c], cur[c]) for c in cols})
            rows_changed, cells = int(diff.any(axis=1).sum()), int(diff.to_numpy().sum())
        no_effect = bool(cols or row_op) and rows_changed == 0 and cells == 0
        desc = describe_step(step)
        report.append({
            "op": op,
            "description": desc + " (matched no rows, nothing changed.)" if no_effect else desc,
            "no_effect": no_effect,
            "rows_before": rows_before,
            "rows_after": rows_after,
            "rows_changed": rows_changed,
            "cells_changed": cells,
            "columns": _affected(step),
            "warning_ids": list(step.get("warning_ids", [])),
            "note": step.get("note", ""),
        })
    return cur.reset_index(drop=True), report
