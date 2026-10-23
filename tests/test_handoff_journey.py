"""T23: the handoff and warning flow end to end through the HTTP API (stub provider or mocked LLM)."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.cleaning_runtime import load_cleaned_dataframe
from api.database import SessionLocal
from api.main import app
from api.models_db import Project, Upload, WarningGroup
from api.routers import ai as ai_router
from api.upload_utils import load_raw_upload_dataframe

PW = "password123"
DESC = "Improve the percentage of patients at goal through an outreach workflow."
W_PAD, W_CASE, W_SITE, W_LAB, E_DUP = (
    "whitespace_padding:unit", "case_inconsistent:unit", "case_inconsistent:site",
    "missing_pct:lab_value", "duplicate_id:encounter_id",
)
ANALYSES = [
    {"id": "d1", "template": "descriptive_summary", "display_name": "Goal summary", "question": "q",
     "rationale": "r", "parameters": {"value_cols": ["at_goal"]}},
    {"id": "p1", "template": "before_after_pct", "display_name": "Pre/post goal", "question": "q", "rationale": "r",
     "parameters": {"group_col": "period", "outcome_col": "at_goal", "pre_val": "pre", "post_val": "post"}},
]
DESIGN_TURN = {
    "message": "ok", "reasoning": "r", "confirmed": False, "sufficient_to_continue": True,
    "design": {"aim": "Raise goal attainment", "population": "Patients", "intervention": {"present": True, "description": "Outreach", "start_date": "2025-01-01"},
               "primary_outcome": {"label": "At goal", "column": "at_goal", "kind": "proportion"}, "comparison": "pre-post",
               "time_structure": {"has_dates": False}, "group_column": "period", "pre_label": "pre", "post_label": "post",
               "plain_restatement": "You are comparing the goal rate.", "sufficient_to_continue": True},
}


def make_csv(dup: bool = False) -> bytes:
    rows = ["encounter_id,period,unit,site,at_goal,lab_value"]
    for i in range(1, 61):
        unit = " ICU " if i % 7 == 0 else "ICU"
        site = ("North", "NORTH", "north")[i % 3]
        lab = "" if i % 5 == 0 else str(10 + i % 9)
        rows.append("%d,%s,%s,%s,%d,%s" % (i, "pre" if i <= 30 else "post", unit, site, i % 2, lab))
    if dup:  # same encounter_id as row 60, different values: only subset-dedupe removes it
        rows.append("60,post, ICU ,north,0,12")
    return ("\n".join(rows) + "\n").encode()


def _use(monkeypatch, provider, key):
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db: (provider, key, None, "m"))


@pytest.fixture
def stub_ai(monkeypatch):
    _use(monkeypatch, "stub", "stub")


@pytest.fixture
def no_ai(monkeypatch):
    _use(monkeypatch, "openrouter", None)


@pytest.fixture
def llm_ai(monkeypatch, mock_llm):
    _use(monkeypatch, "openrouter", "k")
    return mock_llm


def _register(client, email="owner@example.com"):
    r = client.post("/auth/register", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text


def _intake(client, csv: bytes, title="Handoff QI"):
    r = client.post("/projects/intake", data={"title": title, "description": DESC},
                    files={"file": ("d.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    j = r.json()
    return j["project"]["id"], j["upload"]["id"], j["upload"]


def _upload(uid) -> Upload:
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        db.expunge(u)
        return u


def _plan_stale(pid) -> bool:
    with SessionLocal() as db:
        return bool(json.loads(db.get(Project, pid).ai_analysis_plan).get("stale"))


def _states(client, uid) -> dict:
    return {f["flag_id"]: f["state"] for f in client.get(f"/upload/{uid}/flag-states").json()["flags"]}


def _group(client, uid, ids, action, text=None):
    r = client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ids, "action": action, "text": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _message(client, gid, text, warning_id=None):
    body = {"message": text}
    if warning_id:
        body["warning_id"] = warning_id
    r = client.post("/ai/advisor/groups/%d/messages" % gid, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _confirm(client, gid, proposal_id, **kw):
    return client.post("/ai/advisor/groups/%d/confirm" % gid, json={"proposal_id": proposal_id, **kw})


def _design(client, pid, mock=None):
    """Design confirmation (design comes from the stub or a queued LLM turn); moves the project to review."""
    if mock is not None:
        mock.push(DESIGN_TURN)
    assert client.post("/ai/clarify/%d" % pid, json={"message": "The period column has pre and post."}).status_code == 200
    assert client.post("/ai/clarify/%d" % pid, json={"confirm": True}).status_code == 200


def _plan(client, pid):
    r = client.post("/ai/recommend-plan/%d" % pid, json={"confirm": True, "analyses": ANALYSES})
    assert r.status_code == 200 and r.json()["confirmed"] is True, r.text


def _docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return z.read("word/document.xml").decode("utf-8")


def _pdf_text(content: bytes) -> str:
    import pypdf
    return " ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(content)).pages)


def _norm(text: str) -> str:
    return " ".join(text.split())


def test_advisor_on_full_journey(auth_client, stub_ai, monkeypatch, mock_llm):
    c = auth_client
    pid, uid, up = _intake(c, make_csv())
    _design(c, pid)
    ids = {f["id"]: f["severity"] for f in up["quality_flags"]}
    assert {W_PAD, W_CASE, W_SITE, W_LAB} <= set(ids) and E_DUP not in ids

    # The handoff exists straight after upload and names every flag.
    h = c.get("/upload/%d/handoff" % uid).json()
    assert h["status"] == "current" and h["markdown"]
    for fid in ids:
        assert fid in h["markdown"], fid
    raw_before = Path(_upload(uid).encrypted_path).read_bytes()
    checksum = _upload(uid).checksum_sha256
    assert hashlib.sha256(raw_before).hexdigest() != "" and checksum

    # Gating blocks while anything is unhandled.
    assert c.post("/ai/recommend-plan/%d" % pid, json={"confirm": True, "analyses": ANALYSES}).status_code == 409

    # Acknowledge two warnings in one call.
    ack = c.post("/upload/%d/warnings/acknowledge" % uid, json={"flag_ids": [W_SITE, W_LAB]})
    assert ack.status_code == 201 and ack.json()["status"] == "handled", ack.text
    assert {_states(c, uid)[W_SITE], _states(c, uid)[W_LAB]} == {"handled"}

    # Clarify two others: the advisor speaks first, covering both warnings.
    gid = _group(c, uid, [W_PAD, W_CASE], "clarify", "Tidy the unit column.")
    first = _message(c, gid, "start")
    assert first["needs_user_confirmation"] and {p["warning_id"] for p in first["proposals"]} == {W_PAD, W_CASE}
    thread = c.get("/ai/advisor/groups/%d" % gid).json()
    assert thread["turns"][0]["role"] == "advisor" and thread["group"]["status"] == "discussing"
    assert c.post("/ai/recommend-plan/%d" % pid, json={"confirm": True, "analyses": ANALYSES}).status_code == 409
    assert c.get("/upload/%d/flag-states" % uid).json()["unhandled_warning_count"] == 2

    # The user replies about one warning; the reply maps to it and the earlier proposal stays pending.
    reply = _message(c, gid, "Lower case is fine for unit.", warning_id=W_CASE)
    assert {p["warning_id"] for p in reply["proposals"]} == {W_PAD, W_CASE}
    assert [t["role"] for t in c.get("/ai/advisor/groups/%d" % gid).json()["turns"]] == ["advisor", "user", "advisor"]
    assert c.get("/ai/advisor/groups/%d" % gid).json()["turns"][1]["warning_id"] == W_CASE

    rev_before = c.get("/upload/%d/handoff" % uid).json()["revision"]
    done = _confirm(c, gid, reply["proposal_id"])
    assert done.status_code == 200, done.text
    d = done.json()
    assert d["applied"] and d["group_status"] == "handled" and d["handoff_revision"] == rev_before + 1
    assert {f["state"] for f in d["flag_states"]["flags"]} == {"handled"}

    h = c.get("/upload/%d/handoff" % uid).json()
    assert [s["op"] for s in h["steps"]] == ["trim", "change_case"] and h["revision"] == rev_before + 1
    assert h["change_log"][-1]["kind"] == "apply" and h["change_log"][-1]["group_id"] == gid
    assert "owner@example.com" not in (_upload(uid).handoff_md or "")  # emails never enter the document
    assert _states(c, uid) == {fid: "handled" for fid in ids}

    # Cleaned data differs from raw; the raw encrypted file is untouched.
    u = _upload(uid)
    raw_df, clean_df = load_raw_upload_dataframe(u), load_cleaned_dataframe(u)
    assert set(raw_df["unit"]) == {"ICU", " ICU "} and set(clean_df["unit"]) == {"icu"}
    assert Path(u.encrypted_path).read_bytes() == raw_before and u.checksum_sha256 == checksum

    # Gating passes; plan, validate and run all see the cleaned frame.
    assert c.get("/upload/%d/flag-states" % uid).json()["unhandled_warning_count"] == 0
    _plan(c, pid)
    seen = []
    import api.routers.analyze as analyze_mod
    real_load = analyze_mod.load_upload_dataframe
    monkeypatch.setattr(analyze_mod, "load_upload_dataframe", lambda u, *a, **k: (seen.append(real_load(u, *a, **k)), seen[-1])[1])
    v = c.post("/analyze/validate-plan/%d" % pid, json={"upload_id": uid, "analyses": ANALYSES})
    assert v.status_code == 200 and all(i["ok"] for i in v.json()["items"]), v.text
    run = c.post("/analyze/run-plan/%d" % pid, json={"upload_id": uid, "analyses": ANALYSES})
    assert run.status_code == 200 and run.json()["failures"] == [], run.text
    assert seen and all(set(df["unit"]) == {"icu"} for df in seen)
    monkeypatch.setattr(analyze_mod, "load_upload_dataframe", real_load)

    runs = run.json()["runs"]
    dc = runs[0]["data_changes"]
    assert [s["rows_before"] for s in dc["steps"]] == [60, 60] and dc["steps"][0]["cells_changed"] == 8
    assert dc["steps"][1]["cells_changed"] == 60 and "Decision" not in json.dumps(dc["steps"])

    # Reports and exported scripts list the change with row counts.
    docx = c.get("/report/project/%d/docx" % pid)
    assert docx.status_code == 200
    text = _norm(_docx_text(docx.content))
    assert "Data changes applied" in text and "Rows before 60, after 60" in text
    pdf = c.get("/report/project/%d/pdf" % pid)
    assert pdf.status_code == 200
    ptext = _norm(_pdf_text(pdf.content))
    assert "Data changes applied" in ptext and "Rows before 60" in ptext
    with SessionLocal() as db:
        from api.models_db import AnalysisRun
        codes = [r.code_r for r in db.query(AnalysisRun).filter_by(project_id=pid).all()]
    assert codes and all(code.startswith("# Data changes applied before this analysis") for code in codes)

    # Undo through the advisor reopens the group and blocks until it is confirmed.
    assert not _plan_stale(pid)
    # (the stub never proposes an undo, so this one turn comes from a mocked model)
    _use(monkeypatch, "openrouter", "k")
    mock_llm.push({"message": "I would remove the lower-casing.", "mode": "undo", "unapplied_notes": [],
                   "proposals": [{"warning_id": W_CASE, "summary": "Undo the lower-casing.", "steps": []}]})
    undo = _message(c, gid, "Actually, undo the lower-casing.", warning_id=W_CASE)
    assert undo["group_status"] == "discussing" and undo["mode"] == "undo"
    assert c.get("/upload/%d/flag-states" % uid).json()["unhandled_warning_count"] >= 1
    blocked = c.post("/analyze/run-plan/%d" % pid, json={"upload_id": uid, "analyses": ANALYSES})
    assert blocked.status_code == 409
    again = _confirm(c, gid, undo["proposal_id"])
    assert again.status_code == 200 and again.json()["group_status"] == "handled"
    # A handoff change marks the confirmed plan stale; run-plan then needs reconfirmation.
    assert _upload(uid).handoff_revision > rev_before + 1 and _plan_stale(pid)
    assert c.post("/analyze/run-plan/%d" % pid, json={"upload_id": uid, "analyses": ANALYSES}).status_code == 409
    assert c.get("/upload/%d/handoff" % uid).json()["change_log"][-1]["kind"] == "undo"
    assert [x["op"] for x in c.get("/upload/%d/handoff" % uid).json()["steps"]] == ["trim"]
    assert set(load_cleaned_dataframe(_upload(uid))["unit"]) == {"ICU"}
    _plan(c, pid)  # reconfirming clears the stale flag
    assert not _plan_stale(pid)
    assert c.post("/analyze/run-plan/%d" % pid, json={"upload_id": uid, "analyses": ANALYSES}).status_code == 200


def test_two_clarify_groups_are_independent(auth_client, stub_ai):
    c = auth_client
    _, uid, _ = _intake(c, make_csv())
    g1 = _group(c, uid, [W_PAD], "clarify", "Trim the spaces.")
    g2 = _group(c, uid, [W_CASE], "clarify", "Fold the case.")
    assert c.post("/upload/%d/warning-groups" % uid, json={"flag_ids": [W_PAD], "action": "clarify"}).status_code == 409
    r1, r2 = _message(c, g1, "start"), _message(c, g2, "start")
    assert [p["warning_id"] for p in r1["proposals"]] == [W_PAD]
    assert [p["warning_id"] for p in r2["proposals"]] == [W_CASE]
    groups = {g["id"]: g for g in c.get("/upload/%d/warning-groups" % uid).json()["groups"]}
    assert groups[g1]["text"] != groups[g2]["text"]
    assert _confirm(c, g1, r2["proposal_id"]).status_code == 409  # a proposal never crosses groups
    assert _confirm(c, g1, r1["proposal_id"]).status_code == 200
    st = _states(c, uid)
    assert st[W_PAD] == "handled" and st[W_CASE] == "discussing"


def test_error_flag_needs_a_confirmed_fix_and_recheck(auth_client, llm_ai):
    c = auth_client
    pid, uid, up = _intake(c, make_csv(dup=True))
    _design(c, pid, llm_ai)
    assert any(f["id"] == E_DUP and f["severity"] == "ERROR" for f in up["quality_flags"])
    # Acknowledging an ERROR is refused and a lone acknowledgement of the rest does not clear it.
    r = c.post("/upload/%d/warnings/acknowledge" % uid, json={"flag_ids": [E_DUP]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "error_flag_requires_clarify"
    warn = [f["id"] for f in up["quality_flags"] if f["severity"] == "WARNING"]
    assert c.post("/upload/%d/warnings/acknowledge" % uid, json={"flag_ids": warn}).status_code == 201
    assert c.get("/upload/%d/flag-states" % uid).json()["unresolved_error_count"] == 1
    assert c.post("/ai/recommend-plan/%d" % pid, json={"confirm": True, "analyses": ANALYSES}).status_code == 409

    # Clarifying alone (no confirmed data change) does not clear it either.
    gid = _group(c, uid, [E_DUP], "clarify", "These rows are duplicates.")
    llm_ai.push({"message": "Noted.", "mode": "propose", "unapplied_notes": [],
                 "proposals": [{"warning_id": E_DUP, "summary": "Leave as is.", "steps": []}]})
    note_only = _message(c, gid, "Leave it.")
    assert _confirm(c, gid, note_only["proposal_id"]).json()["group_status"] == "handled"
    st = c.get("/upload/%d/flag-states" % uid).json()
    assert st["unresolved_error_count"] == 1 and _states(c, uid)[E_DUP] == "discussing"
    assert c.post("/ai/recommend-plan/%d" % pid, json={"confirm": True, "analyses": ANALYSES}).status_code == 409

    # A confirmed drop_duplicates step makes the re-check pass.
    llm_ai.push({"message": "I would drop the repeated encounter.", "mode": "revise", "unapplied_notes": [],
                 "proposals": [{"warning_id": E_DUP, "summary": "Drop the repeated encounter_id row.",
                                "steps": [{"op": "drop_duplicates", "subset": ["encounter_id"], "keep": "first", "warning_ids": [E_DUP]}]}]})
    fix = _message(c, gid, "Keep only the first row for each encounter_id.")
    assert fix["needs_user_confirmation"] and fix["proposals"][0]["steps"][0]["op"] == "drop_duplicates"
    done = _confirm(c, gid, fix["proposal_id"])
    assert done.status_code == 200 and done.json()["rows_affected"], done.text
    assert done.json()["flag_states"]["unresolved_error_count"] == 0
    u = _upload(uid)
    assert len(load_raw_upload_dataframe(u)) == 61 and len(load_cleaned_dataframe(u)) == 60
    gate = c.get("/projects/%d" % pid)
    assert gate.status_code == 200
    _plan(c, pid)  # reaching the plan phase proves the gate opened
    run = c.post("/analyze/run-plan/%d" % pid, json={"upload_id": uid, "analyses": ANALYSES})
    assert run.status_code == 200 and run.json()["failures"] == [], run.text
    dc = run.json()["runs"][0]["data_changes"]
    assert dc["steps"][0]["rows_before"] == 61 and dc["steps"][0]["rows_after"] == 60 and dc["steps"][0]["rows_removed"] == 1


def test_advisor_off_manual_path(auth_client, no_ai):
    c = auth_client
    pid, uid, up = _intake(c, make_csv())
    assert c.get("/upload/%d/handoff" % uid).json()["markdown"]  # built without AI
    # Manual design entry: the clarify chat is unavailable, confirm still works.
    assert c.post("/ai/clarify/%d" % pid, json={"message": "hi"}).status_code == 503
    assert c.post("/ai/clarify/%d" % pid, json={"confirm": True}).status_code == 200
    # Clarify is unavailable in a structured way and nothing is created half-way.
    g = _group(c, uid, [W_PAD], "clarify", "Trim.")
    r = c.post("/ai/advisor/groups/%d/messages" % g, json={"message": "start"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "advisor_unavailable"
    assert c.get("/ai/advisor/groups/%d" % g).json()["advisor_available"] is False
    # Acknowledge still works for the rest; the clarify group keeps the gate shut.
    rest = [f["id"] for f in up["quality_flags"] if f["id"] != W_PAD]
    assert c.post("/upload/%d/warnings/acknowledge" % uid, json={"flag_ids": rest}).status_code == 201
    assert c.post("/ai/recommend-plan/%d" % pid, json={"confirm": True, "analyses": ANALYSES}).status_code == 409
    with SessionLocal() as db:
        db.delete(db.get(WarningGroup, g))
        db.commit()
    assert c.post("/upload/%d/warnings/acknowledge" % uid, json={"flag_ids": [W_PAD]}).status_code == 201
    r = c.post("/ai/recommend-plan/%d" % pid, json={"confirm": True, "analyses": ANALYSES})
    assert r.status_code == 200, r.text
    run = c.post("/analyze/run-plan/%d" % pid, json={"upload_id": uid, "analyses": ANALYSES})
    assert run.status_code == 200 and run.json()["failures"] == [], run.text
    interp = c.post("/ai/interpret-results/%d" % pid)
    assert interp.status_code == 503 and interp.json()["error"]["code"] == "advisor_unavailable"
    assert c.get("/report/project/%d/docx" % pid).status_code == 200


def test_phi_upload_gate_still_blocks_without_ai(auth_client, no_ai):
    r = auth_client.post("/projects/intake", data={"title": "PHI", "description": DESC},
                         files={"file": ("p.csv", b"patient_name,mrn,val\nJane Doe,100234,10\nJohn Roe,100567,12\n", "text/csv")})
    assert r.status_code == 422, r.text


def _replace(c, pid, uid, csv):
    r = c.post("/upload/%d/replace/%d" % (pid, uid), files={"file": ("d.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def _setup_with_change(c):
    """An upload with one confirmed trim, the rest acknowledged, and a confirmed plan."""
    pid, uid, up = _intake(c, make_csv())
    _design(c, pid)
    gid = _group(c, uid, [W_PAD], "clarify", "Trim.")
    p = _message(c, gid, "start")
    assert _confirm(c, gid, p["proposal_id"]).status_code == 200
    rest = [f["id"] for f in up["quality_flags"] if f["id"] != W_PAD]
    assert c.post("/upload/%d/warnings/acknowledge" % uid, json={"flag_ids": rest}).status_code == 201
    _plan(c, pid)
    return pid, uid, up


def test_reupload_identical_keep_and_fresh(auth_client, stub_ai):
    c = auth_client
    pid, uid, up = _setup_with_change(c)
    old_steps = c.get("/upload/%d/handoff" % uid).json()["steps"]
    assert len(old_steps) == 1 and not _plan_stale(pid)

    b = _replace(c, pid, uid, make_csv())
    assert b["same_as_previous"] and b["choice_required"]
    nid = b["id"]
    kept = c.post("/upload/%d/reupload-choice" % nid, json={"choice": "keep"})
    assert kept.status_code == 200, kept.text
    h = kept.json()["handoff"]
    assert h["status"] == "current" and h["steps"] == old_steps and h["change_log"][-1]["kind"] == "keep_from_previous"
    st = c.get("/upload/%d/flag-states" % nid).json()
    assert st["unhandled_warning_count"] == 0 and st["unresolved_error_count"] == 0
    assert not _plan_stale(pid)
    assert set(load_cleaned_dataframe(_upload(nid))["unit"]) == {"ICU"}

    b2 = _replace(c, pid, nid, make_csv())
    assert b2["choice_required"]
    fresh = c.post("/upload/%d/reupload-choice" % b2["id"], json={"choice": "fresh"})
    assert fresh.status_code == 200 and fresh.json()["handoff"]["steps"] == [] and fresh.json()["handoff"]["revision"] == 1
    assert c.get("/upload/%d/flag-states" % b2["id"]).json()["unhandled_warning_count"] > 0
    assert _plan_stale(pid)


def test_reupload_different_file_history_and_delete_keeps_log(auth_client, stub_ai):
    c = auth_client
    pid, uid, _ = _setup_with_change(c)
    b = _replace(c, pid, uid, make_csv(dup=True))
    assert b["started_fresh"] and not b["same_as_previous"] and not b["choice_required"]
    new = c.get("/upload/%d/handoff" % b["id"]).json()
    assert new["steps"] == [] and new["status"] == "current"
    hist = c.get("/projects/%d/handoff-history" % pid).json()["items"]
    assert [i["upload_id"] for i in hist] == [uid] and hist[0]["status"] == "replaced"
    log_len = hist[0]["change_log_entries"]
    assert log_len >= 2

    # The current handoff cannot be deleted; a replaced one can, and its change log stays.
    assert c.delete("/upload/%d/handoff" % b["id"]).status_code == 409
    assert c.delete("/upload/%d/handoff" % uid).status_code == 200
    item = c.get("/projects/%d/handoff-history" % pid).json()["items"][0]
    assert item["status"] == "deleted" and item["change_log_entries"] == log_len
    gone = c.get("/upload/%d/handoff" % uid).json()
    assert gone["markdown"] is None and gone["read_only"] and len(gone["change_log"]) == log_len


def test_mentor_reads_handoff_read_only_without_email(auth_client, stub_ai):
    c = auth_client
    pid, uid, _ = _setup_with_change(c)
    token = c.post("/share/%d/create" % pid, json={}).json()["token"]
    with TestClient(app) as anon:
        r = anon.get("/share/%s/handoff" % token)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["read_only"] is True and body["markdown"] and body["change_log"]
        assert "owner@example.com" not in json.dumps(body)
        for method in (anon.put, anon.post, anon.delete, anon.patch):
            assert method("/share/%s/handoff" % token).status_code in (404, 405)
        assert anon.post("/ai/advisor/groups/1/messages", json={"message": "hi"}).status_code in (401, 403)
        assert anon.get("/share/%s/handoff" % "not-a-token").status_code == 404


def test_ssn_in_advisor_message_is_scrubbed_before_the_llm(auth_client, llm_ai):
    c = auth_client
    _, uid, _ = _intake(c, make_csv())
    gid = _group(c, uid, [W_PAD], "clarify", "Trim the spaces.")
    llm_ai.push({"message": "Noted.", "mode": "info", "proposals": [], "unapplied_notes": []})
    _message(c, gid, "Patient SSN 123-45-6789 appears in unit; please trim.")
    sent = json.dumps(llm_ai.call_args.kwargs["messages"])
    assert "123-45-6789" not in sent and "<untrusted_data>" in sent
    stored = json.dumps(c.get("/ai/advisor/groups/%d" % gid).json()["turns"])
    assert "123-45-6789" not in stored
    # The opening group text is scrubbed too.
    g2 = _group(c, uid, [W_CASE], "clarify", "Also SSN 987-65-4321 please.")
    llm_ai.push({"message": "Noted.", "mode": "info", "proposals": [], "unapplied_notes": []})
    _message(c, g2, "start")
    assert "987-65-4321" not in json.dumps(llm_ai.call_args.kwargs["messages"])
