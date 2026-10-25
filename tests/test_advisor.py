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
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db, user_id: ("openrouter", "k", None, "m"))


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db, user_id: ("stub", "stub", None, "stub"))


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
    assert d["proposal_id"] == "p_%d_1" % gid and "1 row affected" in d["message"]
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
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db, user_id: ("openrouter", None, None, "m"))
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


# ---------- set_role ----------

ROLE_DEN = {"op": "set_role", "column": "age", "role": "denominator"}


def _roles(uid):
    return json.loads(_upload(uid).column_roles)


def _set_roles(uid, roles):
    with SessionLocal() as db:
        db.get(Upload, uid).column_roles = json.dumps(roles)
        db.commit()


def _propose_and_confirm(client, mock_llm, gid, steps, message="go", wid=W_AGE, mode="propose"):
    mock_llm.push(_out("ok", mode=mode, proposals=[_prop(wid, steps)]))
    d = client.post(MSG % gid, json={"message": message}).json()
    return d, client.post(CONF % gid, json={"proposal_id": d["proposal_id"]})


def test_set_role_read_back_mentions_conflict_and_changes_no_data(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    _set_roles(uid, {"encounter_id": "denominator"})
    mock_llm.push(_out("ok", proposals=[_prop(W_AGE, [ROLE_DEN])]))
    d = auth_client.post(MSG % gid, json={"message": "use age as the denominator"}).json()
    dry = d["proposals"][0]["dry_run"][0]
    assert dry["rows_changed"] == 0 and dry["description"] == "Set the role of column age to denominator."
    assert dry["note"] == "encounter_id is also set as Denominator; the analysis will use age."
    assert "rows affected" not in d["message"] and "encounter_id is also set as Denominator" in d["message"]
    assert _roles(uid) == {"encounter_id": "denominator"}  # nothing changes before Confirm


def test_confirm_writes_role_last_plan_picks_it_and_marks_stale(auth_client, provider, mock_llm):
    from api.dataset_profile import get_effective_profile
    from api.models_db import Project
    from api.staleness import check_and_apply_inputs_fingerprint
    uid, gid = _group(auth_client)
    _set_roles(uid, {"age": "numerator", "encounter_id": "denominator", "unit": "grouping"})
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        p = db.get(Project, u.project_id)
        p.ai_analysis_plan = json.dumps({"analyses": [{"template": "run_chart"}], "confirmed": True, "stale": False})
        check_and_apply_inputs_fingerprint(p, u, db)
        db.commit()
        pid = p.id
    d, r = _propose_and_confirm(auth_client, mock_llm, gid, [ROLE_DEN])
    assert r.status_code == 200, r.text
    assert list(r.json()["column_roles"].items())[-1] == ("age", "denominator")
    roles = _roles(uid)
    assert list(roles)[-1] == "age" and roles["age"] == "denominator"
    assert get_effective_profile(_upload(uid))["candidate_roles"]["denominator"][0] == "age"
    rev = json.loads(_upload(uid).handoff_revisions)[-1]
    assert rev["roles_before"] == {"age": "numerator"}
    with SessionLocal() as db:
        assert json.loads(db.get(Project, pid).ai_analysis_plan)["stale"] is True
    steps = extract_steps(_upload(uid).handoff_md)
    assert steps[0]["op"] == "set_role" and "Set the role of column age to denominator." in _upload(uid).handoff_md


def test_undo_restores_role_unless_resident_changed_it_since(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client, (W_AGE,))
    _set_roles(uid, {"age": "numerator", "unit": "grouping"})
    _propose_and_confirm(auth_client, mock_llm, gid, [ROLE_DEN])
    assert _roles(uid)["age"] == "denominator"
    d, r = _propose_and_confirm(auth_client, mock_llm, gid, [], "undo it", mode="undo")
    assert r.json()["column_roles"]["age"] == "numerator" and _roles(uid)["age"] == "numerator"

    # roles absent before: undo removes the key
    _set_roles(uid, {"unit": "grouping"})
    _propose_and_confirm(auth_client, mock_llm, gid, [ROLE_DEN])
    assert "age" in _roles(uid)
    _propose_and_confirm(auth_client, mock_llm, gid, [], "undo", mode="undo")
    assert "age" not in _roles(uid) and _roles(uid)["unit"] == "grouping"

    # the resident edited the table after the advisor set it: undo leaves their value
    _propose_and_confirm(auth_client, mock_llm, gid, [ROLE_DEN])
    _set_roles(uid, {**_roles(uid), "age": "outcome"})
    _propose_and_confirm(auth_client, mock_llm, gid, [], "undo", mode="undo")
    assert _roles(uid)["age"] == "outcome"


def test_set_role_for_unknown_column_is_not_applied(auth_client, provider, mock_llm):
    uid, gid = _group(auth_client)
    bad = {"op": "set_role", "column": "nope", "role": "denominator"}
    mock_llm.push(_out(proposals=[_prop(W_AGE, [bad])]))
    mock_llm.push(_out(proposals=[_prop(W_AGE, [bad])]))
    d = auth_client.post(MSG % gid, json={"message": "x"}).json()
    assert d["dry_run_error"] and not d["needs_user_confirmation"] and _roles(uid) == {}


def test_role_table_edit_alone_marks_plan_stale_and_empty_roles_keep_fingerprint(auth_client):
    from api.models_db import Project
    from api.staleness import compute_inputs_fingerprint
    uid, _ = _group(auth_client)
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        p = db.get(Project, u.project_id)
        base = compute_inputs_fingerprint(p, u)
        u.column_roles = "{}"
        assert compute_inputs_fingerprint(p, u) == base
        u.column_roles = json.dumps({"age": "date"})  # auto-saved guess, not a decision
        assert compute_inputs_fingerprint(p, u) == base
        u.column_roles = json.dumps({"age": "denominator"})
        assert compute_inputs_fingerprint(p, u) != base
        db.rollback()
