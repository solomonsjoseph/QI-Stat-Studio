from __future__ import annotations

import hashlib
import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.audit import log_action
from api.auth import get_current_user, require_project_owner
from api.config import settings
from api.database import get_db
from api.middleware.phi_scrubber import scan_dataframe_for_phi
from api.models_api import ColumnTypeUpdate, UploadOut
from api.models_db import Project, Upload, User
from api.upload_utils import (
    _allowed_suffix,
    _read_dataframe,
    _safe_storage_key,
    _validate_dataset_shape,
    extract_dictionary_text,
)

router = APIRouter(prefix="/upload", tags=["upload"])
UPLOAD_DIR = Path("uploads_enc")
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_BYTES = 50 * 1024 * 1024


def _require_upload_access(upload_id: int, db: Session, user: User) -> Upload:
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    project = db.get(Project, upload.project_id)
    if user.role != "admin" and (not project or project.owner_user_id != user.id):
        raise HTTPException(status_code=403, detail="Project access denied")
    return upload


def _object_like(series: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)


def _parse_ratio(parsed: pd.Series, total: int) -> float:
    if total == 0:
        return 0.0
    return float(parsed.notna().sum() / total)


def _coerce_datetime(series: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(series, errors="coerce")


def _looks_like_text_date(series: pd.Series) -> bool:
    non_null = series.dropna().head(200)
    if len(non_null) == 0:
        return False
    if _parse_ratio(pd.to_numeric(non_null, errors="coerce"), len(non_null)) >= 0.9:
        return False
    return _parse_ratio(_coerce_datetime(non_null), len(non_null)) >= 0.9


def detect_col_type(col_name: str, series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "Date"
    if _object_like(series) and _looks_like_text_date(series):
        return "Date"
    if any(k in col_name.lower() for k in ["id", "mrn", "patient", "encounter"]):
        return "ID"
    if pd.api.types.is_numeric_dtype(series):
        if series.dropna().isin([0, 1]).all():
            return "Yes/No"
        return "Number"
    unique_lower = series.dropna().astype(str).str.lower().unique()
    if set(unique_lower).issubset({"yes", "no", "true", "false", "0", "1"}):
        return "Yes/No"
    return "Category"


def run_data_quality(df: pd.DataFrame, col_types: dict[str, str], preserved_cols: set[str] = frozenset()) -> List[Dict[str, Any]]:
    flags = []

    for col in df.columns:
        if col_types.get(col) == "Category":
            raw = df[col].dropna().astype(str)
            normalized = raw.str.strip().str.lower()
            if not raw.equals(normalized):
                flags.append({"col": col, "rule": "case_inconsistent", "severity": "WARNING", "msg": f"Mixed case in '{col}' column. These will be normalized automatically during analysis."})

    for col in df.columns:
        pct = df[col].isna().mean() * 100
        if pct > 30:
            if col == "fib4_score":
                flags.append({"col": col, "rule": "missing_pct", "severity": "WARNING", "msg": f"fib4_score: {pct:.1f}% missing — often blank when MASLD screening was not done (expected behavior)."})
                continue
            flags.append({"col": col, "rule": "missing_pct", "severity": "WARNING", "msg": f"{col}: {pct:.1f}% missing — if this is your outcome column, results may be unreliable"})
        elif pct > 5:
            flags.append({"col": col, "rule": "missing_pct", "severity": "WARNING", "msg": f"{col}: {pct:.1f}% missing"})

    for col in df.select_dtypes("number").columns:
        if col_types.get(col) in ("Yes/No", "ID") or df[col].dropna().nunique() <= 2:
            continue
        q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
        iqr = q3 - q1
        n_out = int(((df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)).sum())
        if n_out > 0:
            flags.append({"col": col, "rule": "outlier_count", "severity": "WARNING", "msg": f"{col}: {n_out} outlier(s) outside [{q1 - 1.5 * iqr:.1f}, {q3 + 1.5 * iqr:.1f}]"})

    for col in df.columns:
        series = df[col]
        if col_types.get(col) == "Date" or _object_like(series):
            non_null = series.dropna()
            parsed_dates = _coerce_datetime(non_null)
            if col_types.get(col) == "Date" or _parse_ratio(parsed_dates, len(non_null)) >= 0.9:
                dates = parsed_dates.dropna()
                if len(dates) > 0:
                    monthly = dates.dt.to_period("M").value_counts()
                    date_range = pd.period_range(dates.min().to_period("M"), dates.max().to_period("M"), freq="M")
                    gaps = len(date_range) - len(monthly)
                    if gaps > 0:
                        flags.append({"col": col, "rule": "check_time_gaps", "severity": "WARNING", "msg": f"{gaps} month(s) with no records detected"})

    for col in df.columns:
        series = df[col]
        if col_types.get(col) == "Date" or not _object_like(series) or col in preserved_cols:
            continue
        non_null = series.dropna()
        numeric_ratio = _parse_ratio(pd.to_numeric(non_null, errors="coerce"), len(non_null))
        if numeric_ratio >= 0.9:
            flags.append({"col": col, "rule": "numeric_stored_as_text", "severity": "WARNING", "msg": f"{col}: looks numeric but is stored as text — check for stray characters or a mislabeled column"})
            continue
        date_ratio = _parse_ratio(_coerce_datetime(non_null), len(non_null))
        if date_ratio >= 0.9:
            flags.append({"col": col, "rule": "date_stored_as_text", "severity": "WARNING", "msg": f"{col}: looks like dates but is stored as text — check for stray characters or a mislabeled column"})

    if "encounter_id" in df.columns and df["encounter_id"].duplicated().any():
        flags.append({"col": "encounter_id", "rule": "duplicate_id", "severity": "ERROR", "msg": "Duplicate encounter_id values found"})
    if "period" in df.columns:
        vals = set(df["period"].dropna().astype(str).str.strip().str.lower().unique())
        unexpected = vals - {"pre", "post"}
        if unexpected:
            flags.append({"col": "period", "rule": "unexpected_period_values", "severity": "WARNING", "msg": f"Unexpected period values: {unexpected}"})
    return flags


def _parse_json(raw: str | None, fallback: Any):
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _preview_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(df.head(5).to_json(orient="records", date_format="iso"))


def _upload_out(upload: Upload, preview_rows: list[dict[str, Any]] | None = None) -> UploadOut:
    return UploadOut(
        id=upload.id,
        project_id=upload.project_id,
        filename=upload.filename,
        original_filename=upload.original_filename or upload.filename,
        file_type=upload.file_type,
        size_bytes=upload.size_bytes,
        checksum_sha256=upload.checksum_sha256,
        created_at=upload.created_at,
        col_types=_parse_json(upload.col_types, {}),
        column_map=_parse_json(upload.column_map, {}),
        quality_flags=_parse_json(upload.quality_flags, []),
        acknowledged_flags=_parse_json(upload.acknowledged_flags, None),
        status=upload.status,
        preview_rows=preview_rows or [],
    )


def _enforce_phi_gate(df: pd.DataFrame, dictionary_text: str | None) -> None:
    result = scan_dataframe_for_phi(df, dictionary_text=dictionary_text)
    if result.blocked:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "We found information that may identify a patient. Remove it and upload again.",
                # field_errors is the one detail key the global error handler preserves,
                # so per-column PHI violations ({category}: {message}) ride along in it.
                "field_errors": {v.column: [f"{v.category}: {v.message}"] for v in result.violations},
            },
        )


def _store_upload(
    db: Session,
    project_id: int,
    original_filename: str,
    raw: bytes,
    df: pd.DataFrame,
    preserved_cols: set[str],
    dictionary_filename: str | None = None,
    dictionary_text: str | None = None,
) -> tuple[Upload, dict, dict, list, dict]:
    file_type = _allowed_suffix(original_filename)
    storage_key = _safe_storage_key(project_id, original_filename, raw)
    enc_path = UPLOAD_DIR / storage_key
    col_summary = {col: {"dtype": str(df[col].dtype), "missing_pct": round(df[col].isna().mean() * 100, 1)} for col in df.columns}
    col_types = {col: detect_col_type(col, df[col]) for col in df.columns}
    flags = run_data_quality(df, col_types, preserved_cols)
    enc_path.write_bytes(settings.fernet.encrypt(raw))
    upload = Upload(
        project_id=project_id,
        filename=original_filename,
        original_filename=original_filename,
        file_type=file_type,
        size_bytes=len(raw),
        checksum_sha256=hashlib.sha256(raw).hexdigest(),
        storage_key=storage_key,
        status="active",
        created_at=datetime.utcnow(),
        col_types=json.dumps(col_types),
        column_map=json.dumps({}),
        quality_flags=json.dumps(flags),
        encrypted_path=str(enc_path),
        phi_scan_status="clean",
        dictionary_filename=dictionary_filename,
        dictionary_text=dictionary_text,
    )
    db.add(upload)
    return upload, col_summary, col_types, flags, {col: col_summary[col]["missing_pct"] for col in col_summary}


async def _read_validated_upload_file(file: UploadFile) -> tuple[str, str, bytes, pd.DataFrame, set[str]]:
    original_filename = file.filename or "upload"
    file_type = _allowed_suffix(original_filename)
    if file.size and file.size > MAX_BYTES:
        raise HTTPException(400, "File exceeds 50 MB limit")
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(400, "File exceeds 50 MB limit")
    df, restored_cols = _read_dataframe(raw, file_type)
    _validate_dataset_shape(df)
    return original_filename, file_type, raw, df, restored_cols


async def _read_dictionary_file(file: UploadFile) -> tuple[str, str]:
    original_filename = file.filename or "dictionary"
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(400, "Data dictionary file exceeds 50 MB limit")
    return original_filename, extract_dictionary_text(original_filename, raw)


@router.get("/project/{project_id}", response_model=list[UploadOut])
def list_project_uploads(
    project_id: int,
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    uploads = (
        db.query(Upload)
        .filter(Upload.project_id == project_id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .all()
    )
    return [_upload_out(upload) for upload in uploads]


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _upload_out(_require_upload_access(upload_id, db, user))


@router.post("/{project_id}")
async def upload_file(
    project_id: int,
    file: UploadFile = File(...),
    dictionary: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
):
    original_filename, _file_type, raw, df, restored_cols = await _read_validated_upload_file(file)
    dictionary_filename, dictionary_text = (await _read_dictionary_file(dictionary)) if dictionary else (None, None)
    _enforce_phi_gate(df, dictionary_text)
    upload, col_summary, col_types, flags, missing_pct = _store_upload(
        db, project_id, original_filename, raw, df, restored_cols, dictionary_filename, dictionary_text
    )
    db.commit()
    db.refresh(upload)
    log_action(db, project_id, "upload_created", {"upload_id": upload.id, "file_type": upload.file_type, "size_bytes": upload.size_bytes})
    return {"upload_id": upload.id, "row_count": len(df), "col_summary": col_summary, "col_types": col_types, "quality_flags": flags, "missing_pct": missing_pct, "preview_rows": _preview_rows(df)}


@router.patch("/{upload_id}/acknowledged-flags")
def save_acknowledged_flags(upload_id: int, body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    u = _require_upload_access(upload_id, db, user)
    u.acknowledged_flags = json.dumps(body.get("flags", []))
    db.commit()
    return {"ok": True}


@router.put("/{upload_id}/column-types")
def update_column_types(upload_id: int, body: ColumnTypeUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    u = _require_upload_access(upload_id, db, user)
    u.col_types = json.dumps(body.col_types)
    u.column_map = json.dumps(body.column_map)
    db.commit()
    return {"ok": True}


@router.post("/{project_id}/replace/{upload_id}", response_model=UploadOut)
async def replace_upload(
    project_id: int,
    upload_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    project: Project = Depends(require_project_owner),
    user: User = Depends(get_current_user),
):
    old_upload = _require_upload_access(upload_id, db, user)
    if old_upload.project_id != project_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    if old_upload.status != "active":
        raise HTTPException(status_code=400, detail="Only active uploads can be replaced")
    original_filename, _file_type, raw, df, restored_cols = await _read_validated_upload_file(file)
    old_upload.status = "replaced"
    new_upload, _col_summary, _col_types, _flags, _missing_pct = _store_upload(db, project_id, original_filename, raw, df, restored_cols)
    db.commit()
    db.refresh(new_upload)
    log_action(db, project_id, "upload_replaced", {"old_upload_id": old_upload.id, "upload_id": new_upload.id, "file_type": new_upload.file_type, "size_bytes": new_upload.size_bytes})
    return _upload_out(new_upload, _preview_rows(df))


@router.delete("/{upload_id}")
def delete_upload(upload_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    upload = _require_upload_access(upload_id, db, user)
    upload.status = "deleted"
    if upload.encrypted_path:
        path = Path(upload.encrypted_path)
        if path.exists() and path.is_file():
            path.unlink()
    log_action(db, upload.project_id, "upload_deleted", {"upload_id": upload.id})
    return {"ok": True}
