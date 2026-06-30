import json, io
from pathlib import Path
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from sqlalchemy.orm import Session
import pandas as pd
from api.database import get_db
from api.models_db import Upload
from api.models_api import ColumnTypeUpdate
from api.config import settings

router = APIRouter(prefix="/upload", tags=["upload"])
UPLOAD_DIR = Path("uploads_enc")
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_BYTES = 50 * 1024 * 1024


def detect_col_type(col_name: str, series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "Date"
    # ID check before numeric — column names like encounter_id are identifiers, not measures
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


def run_data_quality(df: pd.DataFrame) -> List[Dict[str, Any]]:
    flags = []
    # normalize period
    if "period" in df.columns:
        raw = df["period"].dropna().astype(str)
        normalized = raw.str.strip().str.lower()
        if not raw.equals(normalized):
            flags.append({"col": "period", "rule": "case_inconsistent",
                          "severity": "WARNING",
                          "msg": "Mixed case in 'period' column (e.g. 'Pre' vs 'pre'). Normalized automatically."})
    # missing % — all missingness is WARNING at upload time.
    # ERROR only raised at analysis time if chosen outcome column >30% missing.
    for col in df.columns:
        pct = df[col].isna().mean() * 100
        if pct > 30:
            if col == "fib4_score":
                flags.append({"col": col, "rule": "missing_pct", "severity": "WARNING",
                              "msg": f"fib4_score: {pct:.1f}% missing — often blank when MASLD screening was not done (expected behavior)."})
                continue
            flags.append({"col": col, "rule": "missing_pct", "severity": "WARNING",
                          "msg": f"{col}: {pct:.1f}% missing — if this is your outcome column, results may be unreliable"})
        elif pct > 5:
            flags.append({"col": col, "rule": "missing_pct", "severity": "WARNING",
                          "msg": f"{col}: {pct:.1f}% missing"})
    # outliers (IQR x1.5)
    for col in df.select_dtypes("number").columns:
        q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
        iqr = q3 - q1
        n_out = int(((df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)).sum())
        if n_out > 0:
            flags.append({"col": col, "rule": "outlier_count", "severity": "WARNING",
                          "msg": f"{col}: {n_out} outlier(s) outside [{q1 - 1.5 * iqr:.1f}, {q3 + 1.5 * iqr:.1f}]"})
    # duplicate encounter_id
    if "encounter_id" in df.columns and df["encounter_id"].duplicated().any():
        flags.append({"col": "encounter_id", "rule": "duplicate_id",
                      "severity": "ERROR", "msg": "Duplicate encounter_id values found"})
    # period values after normalization
    if "period" in df.columns:
        vals = set(df["period"].dropna().str.strip().str.lower().unique())
        unexpected = vals - {"pre", "post"}
        if unexpected:
            flags.append({"col": "period", "rule": "unexpected_period_values",
                          "severity": "WARNING", "msg": f"Unexpected period values: {unexpected}"})
    # check_time_gaps — any month with zero records after resampling
    if "encounter_date" in df.columns:
        dates = pd.to_datetime(df["encounter_date"], errors="coerce").dropna()
        if len(dates) > 0:
            monthly = dates.dt.to_period("M").value_counts()
            date_range = pd.period_range(dates.min().to_period("M"),
                                         dates.max().to_period("M"), freq="M")
            gaps = len(date_range) - len(monthly)
            if gaps > 0:
                flags.append({"col": "encounter_date", "rule": "check_time_gaps",
                              "severity": "WARNING",
                              "msg": f"{gaps} month(s) with no records detected"})
    return flags


@router.post("/{project_id}")
async def upload_file(project_id: int, file: UploadFile = File(...),
                      db: Session = Depends(get_db)):
    if file.size and file.size > MAX_BYTES:
        raise HTTPException(400, "File exceeds 50 MB limit")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(400, f"Unsupported file type: {suffix}")
    raw = await file.read()
    df = pd.read_csv(io.BytesIO(raw)) if suffix == ".csv" else pd.read_excel(io.BytesIO(raw))
    flags = run_data_quality(df)
    enc_path = UPLOAD_DIR / f"{project_id}_{file.filename}.enc"
    enc_path.write_bytes(settings.fernet.encrypt(raw))
    col_summary = {col: {"dtype": str(df[col].dtype),
                         "missing_pct": round(df[col].isna().mean() * 100, 1)}
                   for col in df.columns}
    col_types = {col: detect_col_type(col, df[col]) for col in df.columns}
    upload = Upload(project_id=project_id, filename=file.filename,
                    col_types=json.dumps(col_types),
                    quality_flags=json.dumps(flags),
                    encrypted_path=str(enc_path))
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return {"upload_id": upload.id, "row_count": len(df),
            "col_summary": col_summary, "col_types": col_types, "quality_flags": flags}


@router.put("/{upload_id}/column-types")
def update_column_types(upload_id: int, body: dict,
                        db: Session = Depends(get_db)):
    u = db.query(Upload).get(upload_id)
    if not u:
        raise HTTPException(404)
    u.col_types = json.dumps(body)
    db.commit()
    return {"ok": True}
