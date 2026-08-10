from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pandas as pd
from cryptography.fernet import InvalidToken
from fastapi import HTTPException

from api.config import settings

AllowedUploadType = Literal["csv", "xlsx", "xls"]


def _allowed_suffix(filename: str) -> AllowedUploadType:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix in {"csv", "xlsx", "xls"}:
        return suffix  # type: ignore[return-value]
    display = f".{suffix}" if suffix else "(none)"
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {display}")


def _short_reason(exc: Exception) -> str:
    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return reason[:200]


_LEADING_ZERO_RE = re.compile(r"0\d+")


def _restore_leading_zero_columns(df: pd.DataFrame, raw: bytes) -> set[str]:
    """pandas' default int coercion silently drops the leading zero(s) from
    an all-digit column like a zip code ('02139' -> 2139). This can land the
    column as int64 dtype, or as float64 if any cell in it is blank (a
    missing zip is still NaN, but pandas can only represent "int column with
    a hole" as float64), so both dtypes are candidates -- a float64 column
    is only a candidate when every non-null value is a whole number, since a
    genuinely fractional column was never int-like text to begin with. Only
    those candidate columns are re-read as text (via usecols, not a second
    full-file parse), and restored where their original text was actually
    zero-padded. Returns the set of restored columns so callers can treat
    them as intentionally-preserved identifiers rather than a text-vs-numeric
    data quality problem."""
    candidate_cols = [
        col for col in df.columns
        if pd.api.types.is_integer_dtype(df[col])
        or (pd.api.types.is_float_dtype(df[col]) and (df[col].dropna() % 1 == 0).all())
    ]
    if not candidate_cols:
        return set()
    text_cols = pd.read_csv(io.BytesIO(raw), usecols=candidate_cols, dtype=str)
    restored = {col for col in candidate_cols if text_cols[col].dropna().str.fullmatch(_LEADING_ZERO_RE).any()}
    for col in restored:
        df[col] = text_cols[col]
    return restored


def _read_dataframe(raw: bytes, file_type: str) -> tuple[pd.DataFrame, set[str]]:
    normalized = (file_type or "").lower()
    try:
        if normalized == "csv":
            df = pd.read_csv(io.BytesIO(raw))
            restored = _restore_leading_zero_columns(df, raw)
            return df, restored
        if normalized in {"xlsx", "xls"}:
            return pd.read_excel(io.BytesIO(raw)), set()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse uploaded {normalized or 'unknown'} file: {_short_reason(exc)}",
        ) from exc
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {normalized or 'unknown'}")


def _validate_dataset_shape(df: pd.DataFrame) -> None:
    if len(df.index) == 0:
        raise HTTPException(status_code=400, detail="Uploaded dataset must contain at least one row")
    if len(df.columns) == 0:
        raise HTTPException(status_code=400, detail="Uploaded dataset must contain at least one column")
    empty_columns = [str(col) for col in df.columns if not df[col].notna().any()]
    if empty_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Columns with no values are not allowed: {', '.join(empty_columns)}",
        )


def _safe_storage_key(project_id: int, original_filename: str, raw: bytes) -> str:
    suffix = _allowed_suffix(original_filename)
    return f"{project_id}_{uuid4().hex}.{suffix}.enc"


def load_upload_dataframe(upload) -> pd.DataFrame:
    encrypted_path = getattr(upload, "encrypted_path", None)
    if not encrypted_path:
        raise HTTPException(status_code=400, detail="Uploaded file is missing from storage")
    path = Path(encrypted_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail="Uploaded file is missing from storage")
    try:
        raw = settings.fernet.decrypt(path.read_bytes())
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Could not decrypt uploaded file") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is missing from storage") from exc
    df, _restored = _read_dataframe(raw, getattr(upload, "file_type", None) or "csv")
    _validate_dataset_shape(df)
    return df
