"""QI Stat Advisor chat for a clarify warning group.

The advisor works from the handoff document only (never raw rows). Its proposals are
structured cleaning steps that are validated and dry-run before the user sees them, and are
applied to the handoff only when the user confirms. No AI-written code is ever executed.
"""
from __future__ import annotations

import json
import sys
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from api.ai_key import advisor_failed, advisor_unavailable
from api.ai_prompts import ADVISOR_SYSTEM_V1
from api.audit import log_action
from api.auth import get_current_user
from api.cleaning_steps import STEP_VOCABULARY, StepError, apply_steps, describe_step
from api.database import get_db
from api.flag_ids import flag_id, with_ids
from api.handoff import extract_steps, new_revision_entry, replace_steps, revisions_to_markdown
from api.handoff_service import ensure_handoff
from api.middleware.phi_scrubber import scrub_text
from api.models_api import (
    AdvisorConfirmIn,
    AdvisorConfirmOut,
    AdvisorMessageIn,
    AdvisorModelOut,
    AdvisorReply,
    AdvisorThreadOut,
    AdvisorTurnOut,
)
from api.models_db import Project, Upload, User, WarningGroup
from api.routers import ai as ai_router
from api.routers.upload import _require_upload_access
from api.routers.warning_groups import _group_out, compute_flag_states, mark_group_handled
from api.staleness import check_and_apply_inputs_fingerprint
from api.upload_utils import load_raw_upload_dataframe

router = APIRouter(prefix="/ai/advisor", tags=["advisor"])

MAX_DOC_CHARS = 40000
MAX_HISTORY_TURNS = 20
OPENING = "start"
_LOG_RE = re.compile(r"(## Change log\n\n).*?(\n\n## Machine-readable steps)", re.S)
_KIND = {"propose": "apply", "undo": "undo", "revise": "revise"}


# ---------- helpers ----------

def _loads(raw: Optional[str], default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "field_errors": {}})


def _load_group(db: Session, group_id: int, user: User) -> Tuple[WarningGroup, Upload]:
    group = db.get(WarningGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Warning group not found")
    return group, _require_upload_access(group.upload_id, db, user)


def _available(db: Session, user_id: int) -> bool:
    provider, key, _, _ = ai_router._provider_settings(db, user_id)
    return bool(key) or provider == "local"


def _merge(current: List[dict], proposals: List[dict], mode: str) -> Tuple[List[dict], int, int]:
    """Full step list after applying `proposals`, plus where the new steps start and how many there are."""
    new = [s for p in proposals for s in p["steps"]]
    if mode in ("undo", "revise"):
        ids = {p["warning_id"] for p in proposals}
        keep: List[dict] = []
        pos: Optional[int] = None
        for s in current:
            if set(s.get("warning_ids") or []) & ids:
                if pos is None:
                    pos = len(keep)
            else:
                keep.append(s)
        pos = len(keep) if pos is None else pos
        return keep[:pos] + new + keep[pos:], pos, len(new)
    return list(current) + new, len(current), len(new)


def _dry_run(upload: Upload, candidate: List[dict], start: int, n: int) -> Tuple[Optional[List[dict]], Optional[str]]:
    """Run the whole candidate list on the raw frame (same result as new steps on the cleaned frame)."""
    try:
        _, report = apply_steps(load_raw_upload_dataframe(upload), candidate)
        return report[start:start + n], None
    except StepError as exc:
        if exc.index is not None and 0 <= exc.index < len(candidate):
            return None, "%s: %s." % (describe_step(candidate[exc.index]), exc.message)
        return None, "%s." % exc.message
    except HTTPException:
        raise
    except Exception:  # pandas errors from a step that is valid but does not fit the data
        return None, "The change could not be run on the data."


def _evaluate(out: AdvisorModelOut, group_ids: List[str], only_id: Optional[str], current: List[dict],
              prev_pending: Optional[dict], upload: Upload) -> Dict[str, Any]:
    """Filter, normalise and dry-run a model answer. Returns proposals, mode, candidate steps, error."""
    seen: Dict[str, dict] = {}
    for p in out.proposals:
        if p.warning_id not in group_ids or (only_id and p.warning_id != only_id) or p.warning_id in seen:
            continue  # ids outside the group (or other than the one the user replied about) are ignored
        steps = [dict(s, warning_ids=[p.warning_id]) for s in p.steps]
        summary = p.summary.strip() or "; ".join(describe_step(s) for s in steps if isinstance(s.get("op"), str)) or "No data change."
        seen[p.warning_id] = {"warning_id": p.warning_id, "summary": summary, "steps": steps}
    proposals = list(seen.values())
    mode = out.mode if proposals else "info"
    if mode == "propose" and prev_pending and prev_pending.get("mode") == "propose":
        kept = [dict(p, dry_run=[]) for p in prev_pending.get("proposals", []) if p["warning_id"] not in seen]
        proposals = kept + proposals
    res: Dict[str, Any] = {"proposals": proposals, "mode": mode, "error": None, "candidate": None}
    if mode == "info":
        return res
    candidate, start, n = _merge(current, proposals, mode)
    res["candidate"] = candidate
    report, error = _dry_run(upload, candidate, start, n)
    if error:
        res["error"] = error
        return res
    i = 0
    for p in proposals:
        k = len(p["steps"])
        p["dry_run"] = [dict(r) for r in report[i:i + k]]
        i += k
    _annotate_roles(upload, proposals)
    return res


def _roles_of(upload: Upload) -> Dict[str, str]:
    d = _loads(upload.column_roles, {})
    return d if isinstance(d, dict) else {}


def _set_last(roles: Dict[str, str], col: str, role: Optional[str]) -> None:
    """Remove the column and, for a real role, re-insert it at the end (last saved denominator wins)."""
    roles.pop(col, None)
    if role is not None:
        roles[col] = role


def _role_steps(steps: List[dict]) -> List[dict]:
    return [s for s in steps if s.get("op") == "set_role"]


def _annotate_roles(upload: Upload, proposals: List[dict]) -> None:
    """Add a plain note to each set_role dry-run entry that would leave two denominators."""
    sim = dict(_roles_of(upload))
    for p in proposals:
        for step, entry in zip(p["steps"], p.get("dry_run", [])):
            if step.get("op") != "set_role":
                continue
            col, role = step["column"], step["role"]
            _set_last(sim, col, role)
            others = [c for c, r in sim.items() if r == "denominator" and c != col]
            if role == "denominator" and others:
                entry["note"] = "%s is also set as Denominator; the analysis will use %s." % (
                    " and ".join(others), col)


def _plain_report(proposals: List[dict]) -> str:
    lines = []
    for p in proposals:
        for r in p.get("dry_run", []):
            if r.get("op") == "set_role":
                lines.append("- %s No data changes.%s" % (r["description"], " " + r["note"] if r.get("note") else ""))
            else:
                lines.append("- %s: %d rows affected." % (r["description"], r["rows_changed"]))
    return "Checked on your data:\n" + "\n".join(lines) if lines else ""


def _flags_text(upload: Upload, ids: List[str]) -> str:
    rows = []
    for f in with_ids(_loads(upload.quality_flags, [])):
        if f["id"] in ids:
            rows.append(json.dumps({k: f.get(k) for k in ("id", "severity", "msg", "why", "suggestion") if f.get(k)}))
    return "\n".join(rows) or "(none)"


def _refresh_log(md: str, revisions: List[dict]) -> str:
    return _LOG_RE.sub(lambda m: m.group(1) + revisions_to_markdown(revisions) + m.group(2), md, count=1)


def _claim_pending(db: Session, group_id: int, expected: Optional[str]) -> bool:
    """Compare-and-clear: True only for the one caller that still sees `expected` as the pending proposal."""
    if not expected:
        return False
    res = db.execute(update(WarningGroup).where(WarningGroup.id == group_id, WarningGroup.pending_proposal == expected)
                     .values(pending_proposal=None).execution_options(synchronize_session=False))
    return res.rowcount == 1


def _claim_revision(db: Session, upload_id: int, old: int, new: int) -> bool:
    """Bump the handoff revision only if nobody else has since `old`."""
    res = db.execute(update(Upload).where(Upload.id == upload_id, Upload.handoff_revision == old)
                     .values(handoff_revision=new).execution_options(synchronize_session=False))
    return res.rowcount == 1


def _find_role_before(revisions: List[dict], col: str, role: str) -> Optional[str]:
    """The table value a column had before the latest confirmed step that set it to `role`."""
    for r in reversed(revisions):
        if (r.get("roles_set") or {}).get(col) == role and col in (r.get("roles_before") or {}):
            return r["roles_before"][col]
    return None


def _reopen(upload: Upload, group: WarningGroup, ids: List[str]) -> None:
    group.handled_at = None
    acked = _loads(upload.acknowledged_flags, []) or []
    upload.acknowledged_flags = json.dumps([f for f in acked if flag_id(f) not in ids])


# ---------- endpoints ----------

@router.get("/groups/{group_id}", response_model=AdvisorThreadOut)
def get_thread(group_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    group, _ = _load_group(db, group_id, user)
    pending = _loads(group.pending_proposal, None)
    return AdvisorThreadOut(
        group=_group_out(group),
        turns=[AdvisorTurnOut(**t) for t in _loads(group.advisor_turns, [])],
        pending=AdvisorReply(**pending) if pending else None,
        advisor_available=_available(db, user.id),
    )


@router.post("/groups/{group_id}/messages", response_model=AdvisorReply)
def post_message(group_id: int, body: AdvisorMessageIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    group, upload = _load_group(db, group_id, user)
    if group.action != "clarify":
        raise _err(422, "not_clarify_group", "Only Clarify groups have an advisor conversation.")
    ids: List[str] = _loads(group.flag_ids, [])
    if body.warning_id and body.warning_id not in ids:
        raise _err(422, "unknown_flag_id", "That warning is not part of this group.")

    ai_router._enforce_ai_rate_limit(db, user)
    provider, api_key, api_base, model = ai_router._provider_settings(db, user.id)
    if not api_key and provider != "local":
        raise advisor_unavailable(db, provider, user.id)

    project = db.get(Project, upload.project_id)
    ensure_handoff(db, project, upload)
    turns: List[dict] = _loads(group.advisor_turns, [])
    opening = not turns and body.message.strip().lower() == OPENING
    user_text = (group.text or "") if opening else body.message

    # Everything the user typed and the whole document is scrubbed before it can leave the server.
    clean_user, c1 = scrub_text(user_text, redact_dates=False) if user_text.strip() else ("", 0)
    current = _loads(upload.handoff_steps, [])
    doc, c2 = scrub_text((upload.handoff_md or "")[:MAX_DOC_CHARS])
    flags, c3 = scrub_text(_flags_text(upload, ids))
    steps_txt, c4 = scrub_text(json.dumps(list(enumerate(current))))
    prev_pending = _loads(group.pending_proposal, None)
    pend_txt, c5 = scrub_text(json.dumps(prev_pending.get("proposals", [])) if prev_pending else "(none)")
    history, c6 = [], 0  # stored turns are replayed, so scrub them again (older turns may predate a fix)
    for t in turns[-MAX_HISTORY_TURNS:]:
        txt, c = scrub_text(t["text"], redact_dates=False)
        history.append({"role": "assistant" if t["role"] == "advisor" else "user", "content": txt})
        c6 += c
    if c1 + c2 + c3 + c4 + c5 + c6:
        log_action(db, project.id, "phi_redacted", {"redaction_count": c1 + c2 + c3 + c4 + c5 + c6, "source": "ai_advisor"})

    system = ADVISOR_SYSTEM_V1.format(
        warning_ids=json.dumps(ids), group_flags=ai_router._untrusted(flags),
        handoff_document=ai_router._untrusted(doc), current_steps=ai_router._untrusted(steps_txt),
        pending_proposal=ai_router._untrusted(pend_txt), step_vocabulary=STEP_VOCABULARY,
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    if opening and not clean_user:
        messages.append({"role": "user", "content": "(The resident has not written anything yet. Open the conversation as instructed.)"})
    else:
        tag = "[About warning %s] " % body.warning_id if body.warning_id else ""
        messages.append({"role": "user", "content": tag + clean_user})

    result: Dict[str, Any] = {}
    retried_from = None
    out: Optional[AdvisorModelOut] = None
    for attempt in (0, 1):
        chars = sum(len(m["content"]) for m in messages)
        try:
            out = ai_router._validated_completion(provider, api_key, api_base, model, messages,
                                                  AdvisorModelOut, max_tokens=1800)
        except HTTPException:
            ai_router._record_ai_usage(db, user_id=user.id, project_id=project.id, model=model, prompt_chars=chars, status="error")
            raise
        except Exception:
            ai_router._record_ai_usage(db, user_id=user.id, project_id=project.id, model=model, prompt_chars=chars, status="error")
            raise advisor_failed(sys.exc_info()[1])
        ai_router._record_ai_usage(db, user_id=user.id, project_id=project.id, model=model,
                                   prompt_chars=chars, completion_chars=len(out.message), status="ok")
        result = _evaluate(out, ids, body.warning_id, current, prev_pending, upload)
        if result["error"]:  # error text can quote data values: scrub before it is sent, shown or stored
            result["error"], c = scrub_text(result["error"], redact_dates=False)
            if c:
                log_action(db, project.id, "phi_redacted", {"redaction_count": c, "source": "ai_advisor"})
        if not result["error"] or attempt:
            break
        retried_from = result["error"]
        messages = messages + [
            {"role": "assistant", "content": scrub_text(out.model_dump_json(), redact_dates=False)[0]},
            {"role": "user", "content": "That proposal failed when tried on the data: %s Revise it so it works and still does "
                                        "only what the resident asked, or say it cannot be done and list it in unapplied_notes." % result["error"]},
        ]

    assert out is not None
    text = out.message.strip()
    error = result["error"]
    proposals, mode = result["proposals"], result["mode"]
    if error:  # shown to the user; nothing becomes pending
        proposals, mode = [], "info"
        text += "\n\nThis could not be run on your data: %s Nothing was changed." % error
    elif retried_from:
        text = "My first suggestion could not run on your data (%s) so I revised it.\n\n%s" % (retried_from, text)
    report = _plain_report(proposals)
    if report:
        text += "\n\n" + report
    notes = [n.strip() for n in out.unapplied_notes if n.strip()]
    if notes and "not applied" not in text.lower():
        text += "\n\nNOT applied (outside what I can change): " + "; ".join(notes)

    now = datetime.utcnow()
    if not opening:
        turns.append({"role": "user", "text": clean_user, "warning_id": body.warning_id, "created_at": now.isoformat()})
    turns.append({"role": "advisor", "text": text, "warning_id": body.warning_id, "created_at": now.isoformat()})
    confirm = bool(proposals) and mode != "info"
    reply = AdvisorReply(
        group_id=group.id, group_status="discussing", message=text, proposals=proposals,
        needs_user_confirmation=confirm, proposal_id="p_%d_%d" % (group.id, len(turns)) if confirm else None,
        mode=mode, unapplied_notes=notes, dry_run_error=error,
    )
    group.advisor_turns = json.dumps(turns)
    # Anything that is not a new valid proposal also voids the old one, so an earlier Confirm cannot be replayed.
    group.pending_proposal = (json.dumps(dict(reply.model_dump(mode="json"), base_revision=upload.handoff_revision or 0))
                              if confirm else None)
    if group.status == "handled":
        _reopen(upload, group, ids)
    group.status, group.updated_at = "discussing", now
    db.commit()
    return reply


@router.post("/groups/{group_id}/confirm", response_model=AdvisorConfirmOut)
def confirm(group_id: int, body: AdvisorConfirmIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    group, upload = _load_group(db, group_id, user)
    pending = _loads(group.pending_proposal, None)
    if not pending:
        raise _err(409, "no_pending_proposal", "There is no proposal waiting for confirmation.")
    if pending.get("proposal_id") != body.proposal_id:
        raise _err(409, "stale_proposal", "That proposal is no longer current. Please review the latest one.")
    project = db.get(Project, upload.project_id)

    if body.decline:
        group.pending_proposal, group.updated_at = None, datetime.utcnow()
        db.commit()
        return AdvisorConfirmOut(group_id=group.id, group_status=group.status, applied=False,
                                 handoff_revision=upload.handoff_revision or 0,
                                 flag_states=compute_flag_states(db, upload))

    ensure_handoff(db, project, upload)
    base_rev = upload.handoff_revision or 0
    if pending.get("base_revision", base_rev) != base_rev:
        raise _err(409, "stale_proposal", "The handoff changed since this proposal was made. Please review the latest one.")
    mode = pending.get("mode", "propose")
    proposals = [{"warning_id": p["warning_id"], "summary": p.get("summary", ""),
                  "steps": [dict(s) for s in p.get("steps", [])]} for p in pending.get("proposals", [])]
    current = _loads(upload.handoff_steps, [])
    candidate, start, n = _merge(current, proposals, mode)
    report, error = _dry_run(upload, candidate, start, n) if n or candidate != current else ([], None)
    if error:
        raise _err(422, "step_rejected", "These changes cannot be applied: " + error)
    try:
        md = upload.handoff_md or ""
        if candidate != current:
            md = replace_steps(md, candidate)
        else:
            extract_steps(md)
    except ValueError as exc:
        raise _err(422, "step_rejected", "The handoff document could not take these changes: %s" % exc)

    warning_ids = [p["warning_id"] for p in proposals]
    summary = " ".join(p["summary"] for p in proposals if p["summary"]) or "Decision recorded."
    if candidate == current and mode == "propose":
        summary = "Noted, no data change. " + summary
    rev_no = (upload.handoff_revision or 0) + 1
    rows = {str(start + i): int(r["rows_changed"]) for i, r in enumerate(report or [])}
    entry = new_revision_entry(_KIND.get(mode, "apply"), summary, current, candidate, warning_ids,
                               "user", revision=rev_no)
    entry["group_id"], entry["rows_affected"] = group.id, rows
    roles = _roles_of(upload)
    roles_before: Dict[str, Optional[str]] = {}
    roles_set: Dict[str, str] = {}
    if mode in ("undo", "revise"):
        ids = set(warning_ids)
        removed = [s for s in _role_steps(current) if set(s.get("warning_ids") or []) & ids]
        for st in removed:
            col = st["column"]
            if (roles.get(col) or "none") != st["role"]:
                continue  # the resident changed it since; leave their value
            prev = _find_role_before(_loads(upload.handoff_revisions, []), col, st["role"])
            _set_last(roles, col, prev if prev is not None else None)
    new_steps = [s for p in proposals for s in p["steps"]]
    for st in _role_steps(new_steps):
        col = st["column"]
        roles_before.setdefault(col, roles.get(col))
        _set_last(roles, col, st["role"])
        roles_set[col] = st["role"]
    if roles_before:
        entry["roles_before"], entry["roles_set"] = roles_before, roles_set
    revisions = _loads(upload.handoff_revisions, []) + [entry]

    # Atomic claim: only one confirm can clear the pending proposal and move the revision from base_rev.
    if not _claim_pending(db, group.id, group.pending_proposal) or not _claim_revision(db, upload.id, base_rev, rev_no):
        db.rollback()
        raise _err(409, "stale_proposal", "That proposal was already confirmed or is no longer current.")
    upload.column_roles = json.dumps(roles)
    upload.handoff_steps = json.dumps(candidate)
    upload.handoff_md = _refresh_log(md, revisions)
    upload.handoff_revisions = json.dumps(revisions)
    upload.handoff_revision = rev_no
    upload.handoff_updated_at = datetime.utcnow()
    db.add(upload)
    from api.cleaning_runtime import rebuild_profile
    rebuild_profile(upload, db)  # flags are re-run on the cleaned frame by compute_flag_states below
    check_and_apply_inputs_fingerprint(project, upload, db)
    group.pending_proposal = None
    db.commit()
    log_action(db, project.id, "advisor_confirm", {"group_id": group.id, "revision": rev_no, "mode": mode,
                                                    "step_count": len(candidate), "warning_count": len(warning_ids)})
    mark_group_handled(db, upload, group)
    return AdvisorConfirmOut(group_id=group.id, group_status=group.status, applied=True, handoff_revision=rev_no,
                             rows_affected=rows, flag_states=compute_flag_states(db, upload),
                             column_roles=roles)
