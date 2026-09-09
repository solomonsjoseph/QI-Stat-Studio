from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from api.middleware.phi_scrubber import scrub_text

_DENOM_RE = re.compile(r"(total|denom|opportunit|eligible|encounters|patient[_ ]?days|visits)", re.I)


def _is_numeric_series(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s)


def _is_integral_series(s: pd.Series) -> bool:
    clean = s.dropna()
    if clean.empty:
        return False
    if pd.api.types.is_integer_dtype(clean):
        return True
    if pd.api.types.is_float_dtype(clean):
        return bool(np.isclose(clean, clean.round()).all())
    return False


def _extract_column_definition(col: str, dictionary_text: str | None) -> str | None:
    if not dictionary_text:
        return None
    pattern = re.compile(rf"(?:^|\n)\s*{re.escape(col)}\s*[:\-]\s*([^\n]+)", re.I)
    m = pattern.search(dictionary_text)
    if m:
        return m.group(1).strip()[:300]
    idx = dictionary_text.lower().find(col.lower())
    if idx != -1:
        snippet = dictionary_text[idx : idx + 300].strip()
        first_line = snippet.split("\n")[0]
        return first_line[:300]
    return None


def _calculate_numeric_summary(s: pd.Series) -> dict[str, float] | None:
    clean = pd.to_numeric(s, errors="coerce").dropna()
    if clean.empty:
        return None
    q25, q75 = clean.quantile([0.25, 0.75])
    return {
        "min": float(round(clean.min(), 4)),
        "max": float(round(clean.max(), 4)),
        "mean": float(round(clean.mean(), 4)),
        "median": float(round(clean.median(), 4)),
        "p25": float(round(q25, 4)),
        "p75": float(round(q75, 4)),
    }


def _calculate_date_range(s: pd.Series) -> dict[str, str] | None:
    clean = pd.to_datetime(s, errors="coerce").dropna()
    if clean.empty:
        return None
    return {
        "min": str(clean.min().date()),
        "max": str(clean.max().date()),
    }


def build_profile(
    df: pd.DataFrame,
    col_types: dict[str, str],
    dictionary_text: str | None = None,
) -> dict[str, Any]:
    """Build a structured dataset profile artifact for AI consumption without raw rows."""
    row_count = len(df)
    col_count = len(df.columns)
    dup_rows = int(df.duplicated().sum()) if row_count > 0 else 0

    candidate_roles: dict[str, list[str]] = {
        "date": [],
        "outcome": [],
        "numerator": [],
        "denominator": [],
        "grouping": [],
        "identifier": [],
        "binary": [],
        "pairing_id": [],
    }

    numeric_cols: list[str] = []
    col_data_list: list[dict[str, Any]] = []

    # First pass: column metrics and type-based role heuristics
    for col in df.columns:
        col_str = str(col)
        series = df[col]
        inferred = col_types.get(col_str, "Text")
        non_null = series.dropna()
        missing_count = int(series.isna().sum())
        missing_pct = float(round((missing_count / row_count * 100) if row_count else 0.0, 2))
        unique_count = int(series.nunique(dropna=True))
        unique_ratio = (unique_count / row_count) if row_count else 0.0

        # Sample values: <=5 for categorical/binary with unique_count <= 20; scrubbed
        sample_values: list[str] = []
        if inferred in ("Category", "Yes/No") and unique_count <= 20 and not non_null.empty:
            raw_samples = [str(x) for x in non_null.unique()[:5]]
            sample_values = [scrub_text(s)[0] for s in raw_samples]

        numeric_summary = None
        date_range = None
        malformed_count = 0

        if inferred == "Number" or (_is_numeric_series(series) and inferred != "ID"):
            numeric_summary = _calculate_numeric_summary(series)
            numeric_cols.append(col_str)
            parsed = pd.to_numeric(series, errors="coerce")
            malformed_count = int((series.notna() & parsed.isna()).sum())
        elif inferred == "Date":
            date_range = _calculate_date_range(series)
            parsed_dates = pd.to_datetime(series, errors="coerce")
            malformed_count = int((series.notna() & parsed_dates.isna()).sum())

        # Role assignments
        if inferred == "Date":
            candidate_roles["date"].append(col_str)
        if inferred == "Yes/No":
            candidate_roles["binary"].append(col_str)

        # Identifier: detect_col_type returned "ID" or unique ratio > 0.95 (for non-numeric/date)
        is_id = inferred == "ID" or (inferred not in ("Date", "Number", "Yes/No") and unique_ratio > 0.95 and row_count >= 5)
        if is_id:
            candidate_roles["identifier"].append(col_str)
            # Pairing ID: identifier column whose values repeat (unique ratio < 1)
            if unique_ratio < 1.0 and unique_count >= 2:
                candidate_roles["pairing_id"].append(col_str)

        # Grouping: categorical with 2 <= unique_count <= 10
        if inferred == "Category" and 2 <= unique_count <= 10:
            candidate_roles["grouping"].append(col_str)
        col_def = _extract_column_definition(col_str, dictionary_text)

        col_data_list.append({
            "name": col_str,
            "inferred_type": inferred,
            "roles": [],  # populated after second pass
            "missing_count": missing_count,
            "missing_pct": missing_pct,
            "unique_count": unique_count,
            "sample_values": sample_values,
            "numeric_summary": numeric_summary,
            "date_range": date_range,
            "malformed_count": malformed_count,
            "dictionary_definition": col_def,
        })

    # Second pass: Numerator and Denominator detection
    # Denominator regex rule
    for c in numeric_cols:
        series = pd.to_numeric(df[c], errors="coerce").dropna()
        if series.empty:
            continue
        is_strictly_pos = (series > 0).all()
        is_integral = _is_integral_series(series)
        if is_strictly_pos and is_integral and _DENOM_RE.search(c):
            if c not in candidate_roles["denominator"]:
                candidate_roles["denominator"].append(c)

    # Pairwise comparison: bounded <= 40 numeric columns on head(1000)
    if len(numeric_cols) <= 40 and row_count > 0:
        sample_df = df.head(1000)
        for num_c in numeric_cols:
            num_s = pd.to_numeric(sample_df[num_c], errors="coerce")
            num_clean = num_s.dropna()
            if num_clean.empty or (num_clean < 0).any() or not _is_integral_series(num_clean):
                continue

            for den_c in numeric_cols:
                if num_c == den_c:
                    continue
                den_s = pd.to_numeric(sample_df[den_c], errors="coerce")
                den_clean = den_s.dropna()
                if den_clean.empty or (den_clean <= 0).any() or not _is_integral_series(den_clean):
                    continue

                # Compare row-wise where both are present
                valid = num_s.notna() & den_s.notna()
                if valid.sum() >= 5:
                    ge_ratio = (den_s[valid] >= num_s[valid]).mean()
                    if ge_ratio >= 0.95:
                        if num_c not in candidate_roles["numerator"]:
                            candidate_roles["numerator"].append(num_c)
                        if den_c not in candidate_roles["denominator"]:
                            candidate_roles["denominator"].append(den_c)

    # Outcome: any numeric or binary column not classified as identifier or denominator
    for col in df.columns:
        col_str = str(col)
        is_num = col_str in numeric_cols
        is_bin = col_str in candidate_roles["binary"]
        is_id = col_str in candidate_roles["identifier"]
        is_denom = col_str in candidate_roles["denominator"]
        if (is_num or is_bin) and not is_id and not is_denom:
            candidate_roles["outcome"].append(col_str)

    # Populate "roles" in each column's dict
    for col_info in col_data_list:
        name = col_info["name"]
        col_roles = [role for role, cols in candidate_roles.items() if name in cols]
        col_info["roles"] = col_roles

    return {
        "row_count": row_count,
        "column_count": col_count,
        "duplicate_row_count": dup_rows,
        "columns": col_data_list,
        "candidate_roles": candidate_roles,
    }


def get_upload_profile(upload: Any) -> dict[str, Any]:
    """Return stored dataset_profile if present; otherwise compute on demand for backfill."""
    if getattr(upload, "dataset_profile", None):
        try:
            parsed = json.loads(upload.dataset_profile)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, json.JSONDecodeError):
            pass

    col_types = {}
    if getattr(upload, "col_types", None):
        try:
            col_types = json.loads(upload.col_types)
        except (TypeError, json.JSONDecodeError):
            pass
    dict_text = getattr(upload, "dictionary_text", None)

    from api.upload_utils import load_upload_dataframe

    try:
        df = load_upload_dataframe(upload)
        return build_profile(df, col_types, dict_text)
    except Exception:
        return {
            "row_count": 0,
            "column_count": len(col_types),
            "duplicate_row_count": 0,
            "columns": [
                {
                    "name": k,
                    "inferred_type": v,
                    "roles": [],
                    "missing_count": 0,
                    "missing_pct": 0.0,
                    "unique_count": 0,
                    "sample_values": [],
                    "numeric_summary": None,
                    "date_range": None,
                    "malformed_count": 0,
                    "dictionary_definition": None,
                }
                for k, v in col_types.items()
            ],
            "candidate_roles": {
                "date": [k for k, v in col_types.items() if v == "Date"],
                "outcome": [],
                "numerator": [],
                "denominator": [],
                "grouping": [k for k, v in col_types.items() if v == "Category"],
                "identifier": [k for k, v in col_types.items() if v == "ID"],
                "binary": [k for k, v in col_types.items() if v == "Yes/No"],
                "pairing_id": [],
            },
        }
