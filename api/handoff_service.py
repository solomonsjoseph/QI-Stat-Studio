"""Create and store the handoff document for an upload (skeleton first, optional AI summary)."""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
from sqlalchemy.orm import Session

from api.audit import log_action
from api.flag_ids import flag_id, with_ids
from api.handoff import MAX_EXAMPLES, build_handoff_md, new_revision_entry
from api.middleware.phi_scrubber import scrub_text

log = logging.getLogger(__name__)

SUMMARY_HEADING = "## QI Stat Advisor summary"
_BEFORE = "## Quality warnings"
_MAX_SUMMARY = 1200
_BINARY_OK = {"yes", "no", "true", "false", "0", "1", "0.0", "1.0"}


def _offending(df: pd.DataFrame, flag: dict) -> List[Any]:
    col, rule = flag.get("col"), flag.get("rule")
    if col not in df.columns:
        return []
    s = df[col].dropna()
    st = s.astype(str)
    if rule == "outlier_count":
        x = pd.to_numeric(s, errors="coerce").dropna()
        q1, q3 = x.quantile(0.25), x.quantile(0.75)
        iqr = q3 - q1
        return list(x[(x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)])
    if rule == "whitespace_padding":
        return ["'%s'" % v for v in st[st != st.str.strip()]]
    if rule in ("mixed_types", "numeric_stored_as_text"):
        return list(st[pd.to_numeric(s, errors="coerce").isna()])
    if rule == "date_stored_as_text":
        return list(st[pd.to_datetime(s, errors="coerce").isna()])
    if rule == "case_inconsistent":
        return list(st[st != st.str.strip().str.lower()])
    if rule == "binary_out_of_range":
        return list(st[~st.str.strip().str.lower().isin(_BINARY_OK)])
    if rule == "unexpected_period_values":
        return list(st[~st.str.strip().str.lower().isin({"pre", "post"})])
    if rule == "duplicate_id":
        return list(st[st.duplicated(keep=False)])
    if rule == "nonpositive_denominator":
        return list(s[pd.to_numeric(s, errors="coerce") <= 0])
    return []  # missing_pct, dataset-level and other rules have no single offending value


def flag_examples(df: pd.DataFrame, flags: List[dict]) -> Dict[str, List[Any]]:
    out: Dict[str, List[Any]] = {}
    for f in flags:
        try:  # one bad flag must not break handoff creation
            vals = list(dict.fromkeys(str(v) for v in _offending(df, f)))[:MAX_EXAMPLES]
            if vals:
                out[flag_id(f)] = vals
        except Exception:
            continue
    return out


def _clean_summary(text: str) -> str:
    lines = [" ".join(l.replace("`", "").replace("<!--", "").replace("-->", "").split()).lstrip("#> -").strip()
             for l in str(text).splitlines()]
    return "\n\n".join(l for l in lines if l)[:_MAX_SUMMARY].strip()


def _insert_summary(md: str, summary: str) -> str:
    if not summary or SUMMARY_HEADING in md or _BEFORE not in md:
        return md
    return md.replace(_BEFORE, f"{SUMMARY_HEADING}\n\n{summary}\n\n{_BEFORE}", 1)


def _ai_summary(db: Session, project: Any, skeleton: str) -> str:
    """One AI call over the scrubbed skeleton. Returns "" when the advisor is unavailable or fails."""
    from api.ai_prompts import HANDOFF_SUMMARY_SYSTEM_V1  # lazy: ai router imports are heavy
    from api.routers import ai as ai_router

    model = ""
    chars = 0
    try:
        provider, api_key, api_base, model = ai_router._provider_settings(db)
        if not (api_key or provider == "local"):
            return ""
        clean, count = scrub_text(skeleton)
        if count:
            log_action(db, project.id, "phi_redacted", {"redaction_count": count, "source": "handoff_summary"})
        messages = [
            {"role": "system", "content": HANDOFF_SUMMARY_SYSTEM_V1.format(handoff_document=ai_router._untrusted(clean))},
            {"role": "user", "content": "Summarize this handoff document."},
        ]
        chars = sum(len(m["content"]) for m in messages)
        content = ai_router._llm_completion_nonempty(
            provider, api_key, api_base, model, messages, max_tokens=500, reasoning_effort="low"
        )
        summary = _clean_summary(ai_router._extract_json_object(content).get("summary", ""))
        ai_router._record_ai_usage(db, user_id=None, project_id=project.id, model=model,
                                   prompt_chars=chars, completion_chars=len(content), status="ok")
        return summary
    except Exception:
        log.warning("handoff summary failed (%s); keeping skeleton", type(sys.exc_info()[1]).__name__)
        try:
            if chars:
                ai_router._record_ai_usage(db, user_id=None, project_id=project.id, model=model,
                                           prompt_chars=chars, status="error")
        except Exception:
            pass
        return ""


def create_handoff(db: Session, project: Any, upload: Any, df: pd.DataFrame,
                   flags: List[dict], profile: dict, use_ai: bool = True) -> Any:
    """Build and store a fresh handoff on `upload`. Does not commit. Never raises for AI problems."""
    flags = with_ids(flags)
    col_types = json.loads(upload.col_types or "{}")
    rev = new_revision_entry("created", "Handoff created from upload.", [], [], [], "system", revision=1)
    md = build_handoff_md(
        project_name=project.title, filename=upload.original_filename or upload.filename,
        dictionary_text=upload.dictionary_text, profile=profile, flags=flags, col_types=col_types,
        steps=[], revisions=[rev], examples=flag_examples(df, flags),
    )
    if use_ai:
        md = _insert_summary(md, _ai_summary(db, project, md))
    now = datetime.utcnow()
    upload.handoff_md = md
    upload.handoff_steps = "[]"
    upload.handoff_revision = 1
    upload.handoff_revisions = json.dumps([rev])
    upload.handoff_status = "current"
    upload.handoff_updated_at = now
    upload.dictionary_checksum_sha256 = (
        hashlib.sha256(upload.dictionary_text.encode("utf-8")).hexdigest() if upload.dictionary_text else ""
    )
    return upload


def ensure_handoff(db: Session, project: Any, upload: Any) -> Any:
    """Lazily build the skeleton (no AI) for an old upload with no handoff, then commit."""
    if upload.handoff_status != "none" and upload.handoff_md:
        return upload
    from api.dataset_profile import get_upload_profile
    from api.upload_utils import load_raw_upload_dataframe

    df = load_raw_upload_dataframe(upload)
    flags = json.loads(upload.quality_flags or "[]")
    create_handoff(db, project, upload, df, flags, get_upload_profile(upload), use_ai=False)
    db.commit()
    return upload
