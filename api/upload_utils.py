from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pandas as pd
from cryptography.fernet import InvalidToken
from docx import Document
from fastapi import HTTPException
from pypdf import PdfReader

from api.config import settings

# OWASP File Upload Cheat Sheet: cap the size, and for archive-based formats cap it after decompression.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_DICTIONARY_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 250 * 1024 * 1024   # xlsx and docx are zip files
MAX_EXPANSION_RATIO = 100                # per entry, ignoring entries under 1 MB
MAX_ROWS = 200_000
MAX_COLUMNS = 500
MAX_PDF_PAGES = 200
MAX_DICTIONARY_CHARS = 500_000

AllowedUploadType = Literal["csv", "xlsx", "xls"]
AllowedDictionaryType = Literal["pdf", "docx", "txt"]


def _allowed_suffix(filename: str) -> AllowedUploadType:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix in {"csv", "xlsx", "xls"}:
        return suffix  # type: ignore[return-value]
    display = f".{suffix}" if suffix else "(none)"
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {display}")


async def read_capped(file, limit: int, label: str) -> bytes:
    """Read an upload in chunks and stop as soon as it passes the limit, instead of loading all of it first."""
    chunks, total = [], 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=400, detail=f"{label} is larger than the {limit / (1024 * 1024):g} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def check_zip_container(raw: bytes, label: str) -> None:
    """xlsx and docx are zip files: refuse ones that would expand far beyond their size (zip bombs)."""
    try:
        entries = zipfile.ZipFile(io.BytesIO(raw)).infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError("not a valid zip container") from exc  # callers turn this into their usual parse error
    if sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES or any(
        e.file_size > 1024 * 1024 and e.file_size > MAX_EXPANSION_RATIO * max(e.compress_size, 1) for e in entries
    ):
        raise HTTPException(status_code=400, detail=f"{label} expands to an unsafe size and was not opened")


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
            df = pd.read_csv(io.BytesIO(raw), nrows=MAX_ROWS + 1)
            _validate_size_limits(df)
            restored = _restore_leading_zero_columns(df, raw)
            return df, restored
        if normalized in {"xlsx", "xls"}:
            if normalized == "xlsx":
                check_zip_container(raw, "The spreadsheet")
            df = pd.read_excel(io.BytesIO(raw))
            _validate_size_limits(df)
            return df, set()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse uploaded {normalized or 'unknown'} file: {_short_reason(exc)}",
        ) from exc
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {normalized or 'unknown'}")


def _validate_size_limits(df: pd.DataFrame) -> None:
    if len(df.index) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"The dataset has more than {MAX_ROWS:,} rows. Split it or remove rows that are not needed.")
    if len(df.columns) > MAX_COLUMNS:
        raise HTTPException(status_code=400, detail=f"The dataset has more than {MAX_COLUMNS} columns. Remove columns that are not needed.")


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


def _allowed_dictionary_suffix(filename: str) -> AllowedDictionaryType:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix in {"pdf", "docx", "txt"}:
        return suffix  # type: ignore[return-value]
    display = f".{suffix}" if suffix else "(none)"
    raise HTTPException(status_code=400, detail=f"Unsupported data dictionary file type: {display}")


def extract_dictionary_text(filename: str, raw: bytes) -> str:
    """Extract plain text from a required data-dictionary upload (PDF/DOCX/txt)."""
    suffix = _allowed_dictionary_suffix(filename)
    try:
        if suffix == "txt":
            return raw.decode("utf-8", errors="ignore")[:MAX_DICTIONARY_CHARS]
        if suffix == "docx":
            check_zip_container(raw, "The data dictionary")
            doc = Document(io.BytesIO(raw))
            return "\n".join(p.text for p in doc.paragraphs)[:MAX_DICTIONARY_CHARS]
        if suffix == "pdf":
            reader = PdfReader(io.BytesIO(raw))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise HTTPException(status_code=400, detail=f"The data dictionary has more than {MAX_PDF_PAGES} pages")
            return "\n".join(page.extract_text() or "" for page in reader.pages)[:MAX_DICTIONARY_CHARS]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse uploaded data dictionary ({suffix}): {_short_reason(exc)}",
        ) from exc
    raise HTTPException(status_code=400, detail=f"Unsupported data dictionary file type: {suffix}")


def _load_raw(upload) -> tuple[pd.DataFrame, set[str]]:
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
    df, restored = _read_dataframe(raw, getattr(upload, "file_type", None) or "csv")
    _validate_dataset_shape(df)
    return df, restored


def load_raw_upload_dataframe(upload) -> pd.DataFrame:
    """The uploaded file exactly as read, with no handoff steps applied."""
    return _load_raw(upload)[0]


def load_upload_dataframe(upload, apply_steps: bool = True) -> pd.DataFrame:
    """The frame every analysis path should see: raw upload plus agreed handoff steps.

    Use load_raw_upload_dataframe for upload-time profiling/quality and the handoff builder.
    """
    if not apply_steps or getattr(upload, "handoff_steps", None) in (None, "", "[]"):
        return load_raw_upload_dataframe(upload)
    from api.cleaning_runtime import load_cleaned_dataframe  # lazy: avoids a circular import

    return load_cleaned_dataframe(upload)
