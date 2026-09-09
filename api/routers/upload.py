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
from api.dataset_profile import build_profile
from api.phi_gate import PhiGateResult, scan_upload
from api.models_api import ColumnTypeUpdate, UploadOut
from api.staleness import check_and_apply_inputs_fingerprint
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


def run_data_quality(
    df: pd.DataFrame,
    col_types: dict[str, str],
    preserved_cols: set[str] = frozenset(),
    candidate_roles: dict[str, list[str]] | None = None,
) -> List[Dict[str, Any]]:
    flags: list[dict[str, Any]] = []

    def add_flag(
        col: str,
        rule: str,
        severity: str,
        msg: str,
        why: str,
        suggestion: str,
        blocks: str | None = None,
    ):
        flags.append({
            "col": col,
            "rule": rule,
            "severity": severity,
            "msg": msg,
            "why": why,
            "suggestion": suggestion,
            "blocks": blocks,
        })

    # 1. case_inconsistent
    for col in df.columns:
        if col_types.get(col) == "Category":
            raw = df[col].dropna().astype(str)
            normalized = raw.str.strip().str.lower()
            if not raw.equals(normalized):
                add_flag(
                    col=col,
                    rule="case_inconsistent",
                    severity="WARNING",
                    msg=f"Mixed case in '{col}' column. These will be normalized automatically during analysis.",
                    why="Inconsistent casing can cause categorical levels to be counted separately instead of together.",
                    suggestion="Check capitalization in your data, or rely on automatic case normalization.",
                    blocks=None,
                )

    # 2. missing_pct
    for col in df.columns:
        pct = df[col].isna().mean() * 100
        if pct > 30:
            if col == "fib4_score":
                add_flag(
                    col=col,
                    rule="missing_pct",
                    severity="WARNING",
                    msg=f"fib4_score: {pct:.1f}% missing — often blank when MASLD screening was not done (expected behavior).",
                    why="High missingness is expected for condition-conditional screening scores.",
                    suggestion="Ensure blank cells reflect patients who did not meet screening criteria.",
                    blocks=None,
                )
                continue
            add_flag(
                col=col,
                rule="missing_pct",
                severity="WARNING",
                msg=f"{col}: {pct:.1f}% missing — if this is your outcome column, results may be unreliable",
                why="High missingness in an outcome column can bias statistical estimates and reduce power.",
                suggestion="Verify whether missing values are expected or if data can be retrieved from records.",
                blocks=None,
            )
        elif pct > 5:
            add_flag(
                col=col,
                rule="missing_pct",
                severity="WARNING",
                msg=f"{col}: {pct:.1f}% missing",
                why="Missing observations reduce sample size and may bias subgroup comparisons.",
                suggestion="Check whether data can be retrieved from records or if missingness is random.",
                blocks=None,
            )

    # 3. outlier_count
    for col in df.select_dtypes("number").columns:
        if col_types.get(col) in ("Yes/No", "ID") or df[col].dropna().nunique() <= 2:
            continue
        q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
        iqr = q3 - q1
        n_out = int(((df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)).sum())
        if n_out > 0:
            add_flag(
                col=col,
                rule="outlier_count",
                severity="WARNING",
                msg=f"{col}: {n_out} outlier(s) outside [{q1 - 1.5 * iqr:.1f}, {q3 + 1.5 * iqr:.1f}]",
                why="Extreme outliers can distort mean calculations and inflate standard errors.",
                suggestion="Review outlier values to confirm they are clinically plausible and not data entry errors.",
                blocks=None,
            )

    # 4. check_time_gaps
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
                        add_flag(
                            col=col,
                            rule="check_time_gaps",
                            severity="WARNING",
                            msg=f"{gaps} month(s) with no records detected",
                            why="Calendar gaps between periods can violate continuous-time assumptions in time-series charts.",
                            suggestion="Confirm whether gaps represent zero-volume periods or missing collection intervals.",
                            blocks=None,
                        )

    # 5. numeric_stored_as_text & date_stored_as_text
    for col in df.columns:
        series = df[col]
        if col_types.get(col) == "Date" or not _object_like(series) or col in preserved_cols:
            continue
        non_null = series.dropna()
        numeric_ratio = _parse_ratio(pd.to_numeric(non_null, errors="coerce"), len(non_null))
        if numeric_ratio >= 0.9:
            add_flag(
                col=col,
                rule="numeric_stored_as_text",
                severity="WARNING",
                msg=f"{col}: looks numeric but is stored as text — check for stray characters or a mislabeled column",
                why="Numbers formatted as text cannot be averaged or used in statistical formulas.",
                suggestion="Ensure the column contains only numbers and commas/spaces are removed.",
                blocks=None,
            )
            continue
        date_ratio = _parse_ratio(_coerce_datetime(non_null), len(non_null))
        if date_ratio >= 0.9:
            add_flag(
                col=col,
                rule="date_stored_as_text",
                severity="WARNING",
                msg=f"{col}: looks like dates but is stored as text — check for stray characters or a mislabeled column",
                why="Text dates cannot be ordered chronologically or aggregated by month/week.",
                suggestion="Use a standard date format like YYYY-MM-DD.",
                blocks=None,
            )

    # 6. duplicate_id
    if "encounter_id" in df.columns and df["encounter_id"].duplicated().any():
        add_flag(
            col="encounter_id",
            rule="duplicate_id",
            severity="ERROR",
            msg="Duplicate encounter_id values found",
            why="Duplicate identifiers indicate duplicate records or non-unique encounter tracking.",
            suggestion="Deduplicate your dataset so each encounter appears once.",
            blocks=None,
        )

    # 7. unexpected_period_values
    if "period" in df.columns:
        vals = set(df["period"].dropna().astype(str).str.strip().str.lower().unique())
        unexpected = vals - {"pre", "post"}
        if unexpected:
            add_flag(
                col="period",
                rule="unexpected_period_values",
                severity="WARNING",
                msg=f"Unexpected period values: {unexpected}",
                why="Pre/post analysis requires exactly two comparison periods.",
                suggestion="Ensure period values are coded consistently as pre and post.",
                blocks=None,
            )

    # --- NEW RULES (Step 9) ---

    # 8. whitespace_padding: any string cell differs from its .strip()
    for col in df.columns:
        series = df[col]
        if _object_like(series):
            non_null = series.dropna().astype(str)
            if (non_null != non_null.str.strip()).any():
                add_flag(
                    col=col,
                    rule="whitespace_padding",
                    severity="WARNING",
                    msg=f"Column '{col}' contains values with leading or trailing whitespace.",
                    why="Leading or trailing spaces can cause identical values to be counted as separate categories.",
                    suggestion="Trim whitespace from string values before analysis.",
                    blocks=None,
                )

    # 9. mixed_types: an object column has both numeric-parseable and non-parseable non-null values, each >5%
    for col in df.columns:
        series = df[col]
        if _object_like(series) and col_types.get(col) != "Date":
            non_null = series.dropna()
            if len(non_null) >= 10:
                parsed_num = pd.to_numeric(non_null, errors="coerce")
                num_pct = parsed_num.notna().mean() * 100
                non_num_pct = parsed_num.isna().mean() * 100
                if num_pct > 5 and non_num_pct > 5:
                    add_flag(
                        col=col,
                        rule="mixed_types",
                        severity="WARNING",
                        msg=f"Column '{col}' has mixed types ({num_pct:.1f}% numeric, {non_num_pct:.1f}% text).",
                        why="Columns mixing numbers and text labels cannot be reliably averaged or plotted.",
                        suggestion="Separate numeric measurements from descriptive text labels into separate columns.",
                        blocks=None,
                    )

    # 10. duplicate_rows: fully duplicated rows exist
    if df.duplicated().any():
        n_dup = int(df.duplicated().sum())
        add_flag(
            col="(dataset)",
            rule="duplicate_rows",
            severity="WARNING",
            msg=f"Dataset contains {n_dup} fully duplicate row(s).",
            why="Duplicate records artificially inflate sample sizes and distort proportion estimates.",
            suggestion="Verify whether duplicate rows represent distinct encounters or duplicate submissions.",
            blocks=None,
        )

    # 11 & 12: Denominator and Numerator rules
    from api.dataset_profile import _DENOM_RE
    den_cols: list[str] = []
    num_cols: list[str] = []
    if candidate_roles:
        den_cols = candidate_roles.get("denominator", [])
        num_cols = candidate_roles.get("numerator", [])
    else:
        for c in df.select_dtypes("number").columns:
            if _DENOM_RE.search(c):
                den_cols.append(c)
            elif col_types.get(c) == "Number":
                num_cols.append(c)

    # nonpositive_denominator: a denominator candidate has a value <= 0
    for den in den_cols:
        if den in df.columns:
            vals = pd.to_numeric(df[den], errors="coerce").dropna()
            if (vals <= 0).any():
                add_flag(
                    col=den,
                    rule="nonpositive_denominator",
                    severity="ERROR",
                    msg=f"Denominator column '{den}' has values <= 0.",
                    why="Denominator values in rates and proportions must be strictly positive.",
                    suggestion="Remove or recode rows where the denominator is zero or negative.",
                    blocks="p_chart, u_c_chart",
                )

    # numerator_exceeds_denominator: a numerator/denominator pair has numerator > denominator in any row
    for den in den_cols:
        if den not in df.columns:
            continue
        den_s = pd.to_numeric(df[den], errors="coerce")
        for num in num_cols:
            if num not in df.columns or num == den:
                continue
            num_s = pd.to_numeric(df[num], errors="coerce")
            valid = num_s.notna() & den_s.notna()
            if valid.sum() >= 1 and (num_s[valid] > den_s[valid]).any():
                add_flag(
                    col=num,
                    rule="numerator_exceeds_denominator",
                    severity="ERROR",
                    msg=f"Numerator '{num}' exceeds denominator '{den}' in one or more rows.",
                    why="In proportion metrics, numerator events cannot exceed denominator opportunities.",
                    suggestion="Correct rows where the numerator exceeds the denominator.",
                    blocks="p_chart",
                )
                break

    # 13. binary_out_of_range: a Yes/No-typed column has a third distinct non-null value
    for col in df.columns:
        if col_types.get(col) == "Yes/No":
            vals = set(df[col].dropna().astype(str).str.strip().str.lower().unique())
            valid_bin = {"yes", "no", "true", "false", "0", "1", "0.0", "1.0"}
            invalid = vals - valid_bin
            if invalid or len(vals) > 2:
                add_flag(
                    col=col,
                    rule="binary_out_of_range",
                    severity="WARNING",
                    msg=f"Binary column '{col}' has unexpected or third distinct value(s): {invalid or vals}",
                    why="Binary analyses assume two distinct values representing success or failure.",
                    suggestion="Recode unexpected values to standard Yes or No categories.",
                    blocks=None,
                )

    # 14. sparse_category: a grouping candidate has a level with < 5 rows
    for col in df.columns:
        if col_types.get(col) == "Category" or (candidate_roles and col in candidate_roles.get("grouping", [])):
            counts = df[col].dropna().value_counts()
            if 2 <= len(counts) <= 10:
                sparse = counts[counts < 5]
                if not sparse.empty:
                    add_flag(
                        col=col,
                        rule="sparse_category",
                        severity="WARNING",
                        msg=f"Grouping column '{col}' has level(s) with < 5 rows: {dict(sparse)}",
                        why="Subgroups with fewer than 5 rows yield unstable statistical estimates.",
                        suggestion="Combine small categories into an 'Other' group or interpret with caution.",
                        blocks=None,
                    )

    # 15, 16, 17: Date-related checks
    date_cols = [c for c in df.columns if col_types.get(c) == "Date"]
    now_dt = pd.Timestamp.now()
    for col in date_cols:
        parsed_dates = _coerce_datetime(df[col].dropna()).dropna()
        if parsed_dates.empty:
            continue

        # unexpected_date_range: any parsed date is in the future
        if (parsed_dates > now_dt).any():
            future_count = int((parsed_dates > now_dt).sum())
            add_flag(
                col=col,
                rule="unexpected_date_range",
                severity="WARNING",
                msg=f"Date column '{col}' has {future_count} date(s) in the future.",
                why="Future dates indicate system clock misconfiguration or data entry error.",
                suggestion="Verify and correct date entries that occur in the future.",
                blocks=None,
            )

        # insufficient_time_points: < 12 aggregated periods
        if parsed_dates.dt.to_period("M").nunique() < 12:
            add_flag(
                col=col,
                rule="insufficient_time_points",
                severity="WARNING",
                msg=f"Date column '{col}' has fewer than 12 monthly periods.",
                why="Statistical process control charts require at least 12 periods to establish control limits.",
                suggestion="Collect more historical time periods, or use a run chart instead of a control chart.",
                blocks=None,
            )

        # uneven_time_intervals: consecutive parsed dates have >2 distinct gap lengths
        sorted_dates = parsed_dates.drop_duplicates().sort_values()
        if len(sorted_dates) >= 4:
            diffs = sorted_dates.diff().dropna().dt.days
            if diffs.nunique() > 2:
                add_flag(
                    col=col,
                    rule="uneven_time_intervals",
                    severity="WARNING",
                    msg=f"Date column '{col}' has irregular gap intervals between observations.",
                    why="Irregular observation intervals violate regular sampling assumptions in time series.",
                    suggestion="Aggregate observations to a regular interval such as weekly or monthly.",
                    blocks=None,
                )

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
        column_roles=_parse_json(upload.column_roles, {}),
        quality_flags=_parse_json(upload.quality_flags, []),
        acknowledged_flags=_parse_json(upload.acknowledged_flags, None),
        status=upload.status,
        preview_rows=preview_rows or [],
        dataset_profile=_parse_json(upload.dataset_profile, None),
    )

def _enforce_phi_gate(
    df: pd.DataFrame,
    dictionary_text: str | None,
    db: Session | None = None,
    project_id: int | None = None,
) -> PhiGateResult:
    result = scan_upload(df, dictionary_text=dictionary_text)
    if result.status in ("blocked", "error"):
        if db is not None and project_id is not None:
            categories = sorted({f.category for f in result.findings})
            sources = sorted({f.source for f in result.findings})
            log_action(db, project_id, "upload_blocked_phi", {"categories": categories, "sources": sources})
            db.commit()

        if result.status == "blocked":
            msg = "We can't process this file because it may contain patient-identifying information. Remove all names, MRNs, and other PHI, then upload it again."
        else:
            msg = "We couldn't complete the safety check on this file, so we can't process it. Try uploading it again."

        field_errors: dict[str, list[str]] = {}
        for f in result.findings:
            key = f.column if f.column is not None else "dictionary"
            field_errors.setdefault(key, []).append(f"{f.category}: {f.message}")

        raise HTTPException(
            status_code=422,
            detail={
                "message": msg,
                "field_errors": field_errors,
            },
        )
    return result


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
    profile = build_profile(df, col_types, dictionary_text)
    # Rejection happens in _enforce_phi_gate before _store_upload is called, so nothing is written to uploads_enc/ on rejection.
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
        column_roles=json.dumps({}),
        quality_flags=json.dumps(flags),
        dataset_profile=json.dumps(profile),
        encrypted_path=str(enc_path),
        phi_scan_status="passed",
        dictionary_filename=dictionary_filename,
        dictionary_text=dictionary_text,
    )
    db.add(upload)
    return upload, col_summary, col_types, flags, {col: col_summary[col]["missing_pct"] for col in col_summary}, profile


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


async def _read_dictionary_file(file: UploadFile | None) -> tuple[str | None, str | None]:
    if file is None:
        return None, None
    original_filename = file.filename or "dictionary"
    raw = await file.read()
    if not raw:
        return None, None
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
    dictionary_filename, dictionary_text = await _read_dictionary_file(dictionary)
    _enforce_phi_gate(df, dictionary_text, db=db, project_id=project_id)
    upload, col_summary, col_types, flags, missing_pct, profile = _store_upload(
        db, project_id, original_filename, raw, df, restored_cols, dictionary_filename, dictionary_text
    )
    from api.routers.projects import advance_phase
    advance_phase(db, project, "clarify")
    db.commit()
    db.refresh(upload)
    log_action(db, project_id, "upload_created", {"upload_id": upload.id, "file_type": upload.file_type, "size_bytes": upload.size_bytes})
    return {"upload_id": upload.id, "row_count": len(df), "col_summary": col_summary, "col_types": col_types, "quality_flags": flags, "missing_pct": missing_pct, "preview_rows": _preview_rows(df), "profile": profile}


@router.patch("/{upload_id}/acknowledged-flags")
def save_acknowledged_flags(upload_id: int, body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    u = _require_upload_access(upload_id, db, user)
    u.acknowledged_flags = json.dumps(body.get("flags", []))
    db.commit()
    project = db.get(Project, u.project_id)
    from api.routers.projects import PHASES, _has_unacknowledged_flags, advance_phase
    curr_idx = PHASES.index(project.workflow_phase or "intake") if project and (project.workflow_phase or "intake") in PHASES else 0
    if project and curr_idx >= PHASES.index("review") and not _has_unacknowledged_flags(u):
        advance_phase(db, project, "plan")
    return {"ok": True}


@router.put("/{upload_id}/column-types")
def update_column_types(upload_id: int, body: ColumnTypeUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    u = _require_upload_access(upload_id, db, user)
    u.col_types = json.dumps(body.col_types)
    u.column_map = json.dumps(body.column_map)
    u.column_roles = json.dumps(body.column_roles)
    project = db.get(Project, u.project_id)
    if project:
        check_and_apply_inputs_fingerprint(project, u, db)
    db.commit()
    return {"ok": True}


@router.post("/{project_id}/replace/{upload_id}", response_model=UploadOut)
async def replace_upload(
    project_id: int,
    upload_id: int,
    file: UploadFile = File(...),
    dictionary: UploadFile | None = File(None),
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
    dictionary_filename, dictionary_text = await _read_dictionary_file(dictionary)
    _enforce_phi_gate(df, dictionary_text, db=db, project_id=project_id)
    old_upload.status = "replaced"
    new_upload, _col_summary, _col_types, _flags, _missing_pct, _profile = _store_upload(
        db, project_id, original_filename, raw, df, restored_cols, dictionary_filename, dictionary_text
    )
    check_and_apply_inputs_fingerprint(project, new_upload, db)
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
