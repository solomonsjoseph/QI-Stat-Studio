"""QI Stat Advisor chat: stub provider and a mocked LLM (litellm.completion), no network."""
import json

import pytest

from api.cleaning_runtime import load_cleaned_dataframe
from api.database import SessionLocal
from api.handoff import extract_steps
from api.models_db import AuditLog, Upload
from api.routers import ai as ai_router

CSV = b"encounter_id,age,unit\n1,10,mg\n2,,MG\n3,30, mg \n4,40,mg\n"
W_UNIT, W_AGE = "whitespace_padding:unit", "missing_pct:age"
TRIM = {"op": "trim", "columns": ["unit"]}
MSG = "/ai/advisor/groups/%d/messages"
CONF = "/ai/advisor/groups/%d/confirm"


def _flag(fid, sev="WARNING"):
    rule, col = fid.split(":")
    return {"id": fid, "col": col, "rule": rule, "severity": sev, "msg": "msg for " + fid}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db: ("openrouter", "k", None, "m"))


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db: ("stub", "stub", None, "stub"))


def _group(client, flag_ids=(W_UNIT, W_AGE)):
    pid = client.post("/projects", json={"title": "QI", "description": "d"}).json()["id"]
    r = client.post(f"/upload/{pid}", files={"file": ("d.csv", CSV, "text/csv"),
                    "dictionary": ("dict.txt", b"unit: the unit.", "text/plain")})
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.quality_flags = json.dumps([_flag(i) for i in flag_ids] + [_flag("other:z")])
        u.acknowledged_flags = "[]"
        db.commit()
    g = client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": list(flag_ids), "action": "clarify"})
    assert g.status_code == 201, g.text
    return uid, g.json()["id"]


def _out(message="ok", mode="propose", proposals=(), notes=()):
    return {"message": message, "mode": mode, "proposals": list(proposals), "unapplied_notes": list(notes)}


def _prop(wid, steps, summary="s"):
    return {"warning_id": wid, "summary": summary, "steps": steps}


def _upload(uid):
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        db.expunge(u)
        return u


def test_advisor_goes_first_with_dry_run(auth_client, stub):
    uid, gid = _group(auth_client)
    r = auth_client.post(MSG % gid, json={"message": "start"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["group_status"] == "discussing" and d["needs_user_confirmation"] and d["mode"] == "propose"
    by = {p["warning_id"]: p for p in d["proposals"]}
    assert set(by) == {W_UNIT, W_AGE}
    assert by[W_UNIT]["steps"][0]["op"] == "trim" and by[W_UNIT]["dry_run"][0]["rows_changed"] == 1
    assert by[W_AGE]["steps"] == []  # note only
    assert d["proposal_id"] == "p_%d_1" % gid and "1 rows affected" in d["message"]
    t = auth_client.get(f"/ai/advisor/groups/{gid}").json()
    assert [x["role"] for x in t["turns"]] == ["advisor"] and t["pending"]["proposal_id"] == d["proposal_id"]
    assert t["group"]["status"] == "discussing" and t["advisor_available"]


def test_reply_maps_to_one_warning_and_ignores_outside_ids(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM]), _prop(W_AGE, []), _prop("zzz:q", [TRIM])]))
    d = auth_client.post(MSG % gid, json={"message": "trim the unit please", "warning_id": W_UNIT}).json()
    assert [p["warning_id"] for p in d["proposals"]] == [W_UNIT]
    assert auth_client.post(MSG % gid, json={"message": "x", "warning_id": "zzz:q"}).status_code == 422
    # no warning_id: outside id still dropped, in-group ids kept
    mock_llm.push(_out(proposals=[_prop(W_AGE, []), _prop("zzz:q", [TRIM])]))
    d = auth_client.post(MSG % gid, json={"message": "no change for age"}).json()
    assert {p["warning_id"] for p in d["proposals"]} == {W_UNIT, W_AGE}  # earlier unit proposal kept pending


def test_ambiguous_reply_asks_which_warning(auth_client, provider, mock_llm):
    _, gid = _group(auth_client)
    mock_llm.push(_out("Which warning do you mean?", mode="info"))
    d = auth_client.post(MSG % gid, json={"message": "fix it"}).json()
    assert d["proposals"] == [] and not d["needs_user_confirmation"] and d["proposal_id"] is None


def test_dry_run_failure_is_revised_then_shown(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    bad = {"op": "trim", "columns": ["nope"]}
    base = mock_llm.call_count  # the upload itself made a handoff-summary call
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [bad])]))
    mock_llm.push(_out("Revised.", proposals=[_prop(W_UNIT, [TRIM])]))
    d = auth_client.post(MSG % gid, json={"message": "trim unit"}).json()
    assert mock_llm.call_count - base == 2 and d["needs_user_confirmation"] and "could not run" in d["message"]
    # the retry prompt told the advisor what failed
    retry_msgs = mock_llm.call_args.kwargs["messages"]
    assert "failed when tried on the data" in retry_msgs[-1]["content"]
    # both attempts fail
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [bad])]))
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [bad])]))
    d = auth_client.post(MSG % gid, json={"message": "again"}).json()
    assert d["dry_run_error"] and not d["needs_user_confirmation"] and "Nothing was changed" in d["message"]
    assert _upload(uid).handoff_steps == "[]"


def test_confirm_applies_steps_and_cleaned_frame_changes(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    before = _upload(uid)
    assert list(load_cleaned_dataframe(before)["unit"]) == ["mg", "MG", " mg ", "mg"]
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM]), _prop(W_AGE, [])]))
    pid = auth_client.post(MSG % gid, json={"message": "trim"}).json()["proposal_id"]
    r = auth_client.post(CONF % gid, json={"proposal_id": pid})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["applied"] and d["group_status"] == "handled" and d["rows_affected"] == {"0": 1}
    assert d["handoff_revision"] == before.handoff_revision + 1
    u = _upload(uid)
    assert list(load_cleaned_dataframe(u)["unit"]) == ["mg", "MG", "mg", "mg"]
    steps = extract_steps(u.handoff_md)
    assert steps[0]["op"] == "trim" and steps[0]["warning_ids"] == [W_UNIT]
    rev = json.loads(u.handoff_revisions)[-1]
    assert rev["kind"] == "apply" and rev["actor"] == "user" and rev["group_id"] == gid
    assert set(rev["warning_ids"]) == {W_UNIT, W_AGE} and rev["revision"] == u.handoff_revision
    assert "owner@example.com" not in u.handoff_md
    assert {f["state"] for f in d["flag_states"]["flags"] if f["flag_id"] in (W_UNIT, W_AGE)} == {"handled"}
    assert auth_client.post(CONF % gid, json={"proposal_id": pid}).status_code == 409  # already consumed


def test_confirm_stale_or_missing_proposal_rejected(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    assert auth_client.post(CONF % gid, json={"proposal_id": "p_1"}).json()["error"]["code"] == "no_pending_proposal"
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM])]))
    old = auth_client.post(MSG % gid, json={"message": "trim"}).json()["proposal_id"]
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [{"op": "change_case", "columns": ["unit"], "mode": "lower"}])]))
    new = auth_client.post(MSG % gid, json={"message": "no, lower case"}).json()["proposal_id"]
    assert old != new
    r = auth_client.post(CONF % gid, json={"proposal_id": old})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_proposal"
    assert _upload(uid).handoff_steps == "[]"
    assert auth_client.post(CONF % gid, json={"proposal_id": new, "decline": True}).json()["applied"] is False
    assert auth_client.post(CONF % gid, json={"proposal_id": new}).json()["error"]["code"] == "no_pending_proposal"


def test_note_only_agreement_is_handled_with_note_in_change_log(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client, (W_AGE,))
    mock_llm.push(_out(proposals=[_prop(W_AGE, [], "Leave age missing values as they are")],
                       notes=["Impute age with a model"]))
    d = auth_client.post(MSG % gid, json={"message": "leave it, also impute with a model"}).json()
    assert "NOT applied" in d["message"] and d["unapplied_notes"] == ["Impute age with a model"]
    r = auth_client.post(CONF % gid, json={"proposal_id": d["proposal_id"]})
    assert r.json()["group_status"] == "handled" and r.json()["rows_affected"] == {}
    u = _upload(uid)
    assert extract_steps(u.handoff_md) == [] and u.handoff_steps == "[]"
    assert "Leave age missing values as they are" in u.handoff_md.split("## Change log")[1]


def test_undo_reopens_group_until_confirmed(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client, (W_UNIT,))
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM])]))
    pid = auth_client.post(MSG % gid, json={"message": "trim"}).json()["proposal_id"]
    auth_client.post(CONF % gid, json={"proposal_id": pid})
    base = auth_client.get(f"/upload/{uid}/flag-states").json()["unhandled_warning_count"]  # other:z stays unhandled
    assert base == 1

    mock_llm.push(_out("I would remove the trim.", mode="undo", proposals=[_prop(W_UNIT, [], "Undo the trim")]))
    d = auth_client.post(MSG % gid, json={"message": "undo the trim"}).json()
    assert d["mode"] == "undo" and d["needs_user_confirmation"] and d["group_status"] == "discussing"
    st = auth_client.get(f"/upload/{uid}/flag-states").json()
    assert st["unhandled_warning_count"] == base + 1 and st["flags"][0]["state"] == "discussing"
    assert _upload(uid).acknowledged_flags == "[]"
    assert extract_steps(_upload(uid).handoff_md) != []  # nothing changed yet

    r = auth_client.post(CONF % gid, json={"proposal_id": d["proposal_id"]}).json()
    assert r["group_status"] == "handled" and r["handoff_revision"] == 3
    u = _upload(uid)
    assert extract_steps(u.handoff_md) == [] and list(load_cleaned_dataframe(u)["unit"])[2] == " mg "
    assert json.loads(u.handoff_revisions)[-1]["kind"] == "undo"

    # revise: replace only the steps linked to this warning, keep others
    mock_llm.push(_out(mode="revise", proposals=[_prop(W_UNIT, [{"op": "change_case", "columns": ["unit"], "mode": "upper"}])]))
    d = auth_client.post(MSG % gid, json={"message": "use upper case instead"}).json()
    auth_client.post(CONF % gid, json={"proposal_id": d["proposal_id"]})
    assert [s["op"] for s in extract_steps(_upload(uid).handoff_md)] == ["change_case"]


def test_user_text_and_document_are_scrubbed_before_the_llm(auth_client, provider, mock_llm, monkeypatch):
    uid, gid = _group(auth_client)
    seen = []
    import api.routers.advisor as adv
    real = adv.scrub_text
    monkeypatch.setattr(adv, "scrub_text", lambda t, **k: (seen.append(t), real(t, **k))[1])
    mock_llm.push(_out(proposals=[]))
    auth_client.post(MSG % gid, json={"message": "Patient SSN 123-45-6789 is wrong"})
    assert any("123-45-6789" in t for t in seen)                      # user text scrubbed
    assert any("## Quality warnings" in t for t in seen)               # handoff document scrubbed
    sent = json.dumps(mock_llm.call_args.kwargs["messages"])
    assert "123-45-6789" not in sent and "<untrusted_data>" in sent
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(action="phi_redacted").count() >= 1
    turns = auth_client.get(f"/ai/advisor/groups/{gid}").json()["turns"]
    assert "123-45-6789" not in turns[0]["text"]
    rows = SessionLocal().execute(__import__("sqlalchemy").text("select count(*) from ai_usage_events")).scalar()
    assert rows >= 1


def test_no_key_returns_advisor_unavailable(auth_client, monkeypatch):
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db: ("openrouter", None, None, "m"))
    _, gid = _group(auth_client)
    r = auth_client.post(MSG % gid, json={"message": "start"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "advisor_unavailable"
    assert auth_client.get(f"/ai/advisor/groups/{gid}").json()["advisor_available"] is False


def test_acknowledge_group_rejected_and_ownership(auth_client, stub):
    uid, gid = _group(auth_client)
    ack = auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["other:z"]}).json()["id"]
    r = auth_client.post(MSG % ack, json={"message": "start"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_clarify_group"
    assert auth_client.post(MSG % 9999, json={"message": "start"}).status_code == 404
    auth_client.post(MSG % gid, json={"message": "start"})
    auth_client.post("/auth/logout")
    assert auth_client.post("/auth/register", json={"email": "other@example.com", "password": "password123"}).status_code == 200
    assert auth_client.get(f"/ai/advisor/groups/{gid}").status_code == 403
    assert auth_client.post(MSG % gid, json={"message": "hi"}).status_code == 403
    assert auth_client.post(CONF % gid, json={"proposal_id": "p_1_1"}).status_code == 403


def test_dry_run_error_and_history_are_scrubbed_before_llm(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    bad = {"op": "trim", "columns": ["123-45-6789"]}
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [bad])]))
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [bad])]))
    d = auth_client.post(MSG % gid, json={"message": "trim unit"}).json()
    assert d["dry_run_error"] and "123-45-6789" not in json.dumps(d)
    assert "123-45-6789" not in json.dumps(mock_llm.call_args.kwargs["messages"])  # retry message
    # a stored turn that still holds a raw value (older data) is scrubbed on replay
    with SessionLocal() as db:
        from api.models_db import WarningGroup
        g = db.get(WarningGroup, gid)
        turns = json.loads(g.advisor_turns)
        turns[-1]["text"] += " SSN 123-45-6789"
        g.advisor_turns = json.dumps(turns)
        db.commit()
    mock_llm.push(_out(mode="info"))
    auth_client.post(MSG % gid, json={"message": "next"})
    assert "123-45-6789" not in json.dumps(mock_llm.call_args.kwargs["messages"])


def test_non_proposal_reply_clears_pending(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM])]))
    pid = auth_client.post(MSG % gid, json={"message": "trim"}).json()["proposal_id"]
    mock_llm.push(_out("Fine, leave it.", mode="info"))
    auth_client.post(MSG % gid, json={"message": "actually never mind"})
    assert auth_client.get(f"/ai/advisor/groups/{gid}").json()["pending"] is None
    r = auth_client.post(CONF % gid, json={"proposal_id": pid})
    assert r.status_code == 409 and _upload(uid).handoff_steps == "[]"
    # a failing dry run also voids the earlier proposal
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM])]))
    pid = auth_client.post(MSG % gid, json={"message": "trim"}).json()["proposal_id"]
    bad = {"op": "trim", "columns": ["nope"]}
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [bad])]))
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [bad])]))
    auth_client.post(MSG % gid, json={"message": "something else"})
    assert auth_client.post(CONF % gid, json={"proposal_id": pid}).status_code == 409


def test_double_confirm_applies_once_and_claim_helpers(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM])]))
    pid = auth_client.post(MSG % gid, json={"message": "trim"}).json()["proposal_id"]
    assert auth_client.post(CONF % gid, json={"proposal_id": pid}).status_code == 200
    assert auth_client.post(CONF % gid, json={"proposal_id": pid}).status_code == 409
    u = _upload(uid)
    assert len(json.loads(u.handoff_steps)) == 1

    from api.routers.advisor import _claim_pending, _claim_revision
    from api.models_db import WarningGroup
    mock_llm.push(_out(proposals=[_prop(W_AGE, [])]))
    auth_client.post(MSG % gid, json={"message": "leave age"})
    with SessionLocal() as db:
        raw = db.get(WarningGroup, gid).pending_proposal
        assert raw
        assert _claim_pending(db, gid, "not it") is False
        assert _claim_pending(db, gid, raw) is True
        assert _claim_pending(db, gid, raw) is False  # second claimant loses
        rev = db.get(Upload, uid).handoff_revision
        assert _claim_revision(db, uid, rev + 5, rev + 6) is False
        assert _claim_revision(db, uid, rev, rev + 1) is True
        db.rollback()


def test_confirm_rejected_when_handoff_changed_since_proposal(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM])]))
    pid = auth_client.post(MSG % gid, json={"message": "trim"}).json()["proposal_id"]
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.handoff_revision = (u.handoff_revision or 0) + 1
        db.commit()
    r = auth_client.post(CONF % gid, json={"proposal_id": pid})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_proposal"
    assert _upload(uid).handoff_steps == "[]"


def test_legacy_flags_without_ids_end_to_end(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client, (W_UNIT,))
    legacy = [{"col": "unit", "rule": "whitespace_padding", "severity": "WARNING", "msg": "m"}]
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.quality_flags = json.dumps(legacy)
        db.commit()
    mock_llm.push(_out(proposals=[_prop(W_UNIT, [TRIM])]))
    d = auth_client.post(MSG % gid, json={"message": "trim"}).json()
    assert W_UNIT in json.dumps(mock_llm.call_args.kwargs["messages"])  # flag text reaches the advisor
    r = auth_client.post(CONF % gid, json={"proposal_id": d["proposal_id"]})
    assert r.status_code == 200 and r.json()["group_status"] == "handled"
    assert r.json()["flag_states"]["unhandled_warning_count"] == 0
    mock_llm.push(_out(mode="undo", proposals=[_prop(W_UNIT, [], "Undo")]))
    auth_client.post(MSG % gid, json={"message": "undo"})
    assert _upload(uid).acknowledged_flags == "[]"  # legacy ack removed on reopen
