import json

import pytest

from api.database import SessionLocal
from api.models_db import Project, Upload

CSV = b"encounter_id,age,unit\n1,10,mg\n2,,MG\n3,30,mg\n3,30,mg\n"


def _setup(client):
    pid = client.post("/projects", json={"title": "QI", "description": "d"}).json()["id"]
    r = client.post(f"/upload/{pid}", files={"file": ("d.csv", CSV, "text/csv"),
                    "dictionary": ("dict.txt", b"encounter_id: id. age: years. unit: unit.", "text/plain")})
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    return pid, uid


def _seed(uid, flags):
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.quality_flags = json.dumps(flags)
        u.acknowledged_flags = "[]"
        db.commit()


def _flag(fid, sev="WARNING"):
    return {"id": fid, "col": fid.split(":")[1], "rule": fid.split(":")[0], "severity": sev, "msg": "m"}


@pytest.fixture(autouse=True)
def recheck(monkeypatch):
    """Cleaned-data re-check: by default every seeded flag still fires."""
    import api.cleaning_runtime as cr
    state = {"gone": set()}
    monkeypatch.setattr(cr, "recheck_flags",
                        lambda upload: [f for f in json.loads(upload.quality_flags) if f["id"] not in state["gone"]])
    return state


FLAGS = [_flag("a:x"), _flag("b:y"), _flag("c:z"), _flag("e:age", "ERROR")]


def _states(client, uid):
    return {f["flag_id"]: f for f in client.get(f"/upload/{uid}/flag-states").json()["flags"]}


def test_batch_acknowledge_multiple_and_compat(auth_client):
    pid, uid = _setup(auth_client)
    _seed(uid, FLAGS)
    r = auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x", "b:y"], "text": "ok"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "handled" and r.json()["flag_ids"] == ["a:x", "b:y"]
    st = auth_client.get(f"/upload/{uid}/flag-states").json()
    assert st["unhandled_warning_count"] == 1 and st["unresolved_error_count"] == 1
    assert _states(auth_client, uid)["a:x"]["state"] == "handled"
    with SessionLocal() as db:
        acked = json.loads(db.get(Upload, uid).acknowledged_flags)
    assert [f["id"] for f in acked] == ["a:x", "b:y"] and acked[0] == FLAGS[0]
    assert len(auth_client.get(f"/upload/{uid}/warning-groups").json()["groups"]) == 1


def test_two_clarify_groups_with_different_text(auth_client):
    _, uid = _setup(auth_client)
    _seed(uid, FLAGS)
    g1 = auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["a:x"], "action": "clarify", "text": "one"}).json()
    g2 = auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["b:y"], "action": "clarify", "text": "two"}).json()
    assert (g1["status"], g1["handled_at"]) == ("open", None)
    assert g1["id"] != g2["id"] and (g1["text"], g2["text"]) == ("one", "two")
    s = _states(auth_client, uid)
    assert s["a:x"]["state"] == "open" and s["a:x"]["group_id"] == g1["id"] and s["a:x"]["action"] == "clarify"
    with SessionLocal() as db:
        assert db.get(Upload, uid).acknowledged_flags == "[]"


def test_error_flag_rejected_for_acknowledge_but_ok_for_clarify(auth_client):
    _, uid = _setup(auth_client)
    _seed(uid, FLAGS)
    for path in ("warnings/acknowledge", "warning-groups"):
        body = {"flag_ids": ["a:x", "e:age"]} if path.startswith("warnings") else {"flag_ids": ["e:age"], "action": "acknowledge"}
        r = auth_client.post(f"/upload/{uid}/{path}", json=body)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "error_flag_requires_clarify"
        assert r.json()["error"]["field_errors"]["flag_ids"] == ["e:age"]
    assert auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["e:age"], "action": "clarify"}).status_code == 201
    assert _states(auth_client, uid)["e:age"]["state"] == "open"


def test_unknown_and_already_grouped_ids(auth_client):
    _, uid = _setup(auth_client)
    _seed(uid, FLAGS)
    r = auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["nope:q"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_flag_id"
    assert auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x"]}).status_code == 201
    r = auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x", "b:y"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "flag_already_grouped"
    assert r.json()["error"]["field_errors"]["flag_ids"] == ["a:x"]
    assert len(auth_client.get(f"/upload/{uid}/warning-groups").json()["groups"]) == 1


def test_advances_to_plan_when_all_clear(auth_client):
    pid, uid = _setup(auth_client)
    _seed(uid, FLAGS[:2])
    with SessionLocal() as db:
        db.get(Project, pid).workflow_phase = "review"
        db.commit()
    auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x"]})
    with SessionLocal() as db:
        assert db.get(Project, pid).workflow_phase == "review"
    auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["b:y"]})
    with SessionLocal() as db:
        assert db.get(Project, pid).workflow_phase == "plan"


def test_ownership(client):
    client.post("/auth/register", json={"email": "owner@example.com", "password": "password123"})
    _, uid = _setup(client)
    _seed(uid, FLAGS)
    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get(f"/upload/{uid}/flag-states").status_code == 401
    r = client.post("/auth/register", json={"email": "other@example.com", "password": "password123"})
    assert r.status_code == 200, r.text
    for call in (lambda: client.get(f"/upload/{uid}/flag-states"),
                 lambda: client.get(f"/upload/{uid}/warning-groups"),
                 lambda: client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x"]})):
        assert call().status_code == 403
    assert client.get("/upload/9999/flag-states").status_code == 404


def test_error_resolved_when_recheck_clears_it(auth_client, recheck):
    _, uid = _setup(auth_client)
    _seed(uid, FLAGS)
    auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["e:age"], "action": "clarify"})
    assert _states(auth_client, uid)["e:age"]["state"] == "open"
    recheck["gone"].add("e:age")
    st = auth_client.get(f"/upload/{uid}/flag-states").json()
    assert {f["flag_id"]: f["state"] for f in st["flags"]}["e:age"] == "resolved"
    assert st["unresolved_error_count"] == 0


# ---- T16 gating ----

def _gate(client, pid):
    return client.get(f"/projects/{pid}/resume").json()["gating"]


def test_gating_warnings_handled_no_errors_passes(auth_client):
    pid, uid = _setup(auth_client)
    _seed(uid, [_flag("a:x"), _flag("b:y")])
    g = _gate(auth_client, pid)
    assert (g["unhandled_warning_count"], g["can_continue"]) == (2, False)
    auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x", "b:y"]})
    g = _gate(auth_client, pid)
    assert (g["unhandled_warning_count"], g["unresolved_error_count"], g["can_continue"]) == (0, 0, True)
    assert g["advisor_available"] in (True, False)


def test_error_in_handled_clarify_group_blocks_until_recheck_clears(auth_client, recheck):
    pid, uid = _setup(auth_client)
    _seed(uid, [_flag("e:age", "ERROR")])
    from api.models_db import WarningGroup
    from api.routers.warning_groups import mark_group_handled
    gid = auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["e:age"], "action": "clarify"}).json()["id"]
    with SessionLocal() as db:
        mark_group_handled(db, db.get(Upload, uid), db.get(WarningGroup, gid))
        assert json.loads(db.get(Upload, uid).acknowledged_flags)  # ERROR mirrored into acknowledged_flags
    g = _gate(auth_client, pid)
    assert (g["unresolved_error_count"], g["can_continue"]) == (1, False)
    recheck["gone"].add("e:age")
    g = _gate(auth_client, pid)
    assert (g["unresolved_error_count"], g["can_continue"]) == (0, True)


def test_legacy_acknowledged_flags_pass_but_not_for_errors(auth_client):
    pid, uid = _setup(auth_client)
    flags = [_flag("a:x"), _flag("e:age", "ERROR")]
    _seed(uid, flags)
    auth_client.patch(f"/upload/{uid}/acknowledged-flags", json={"flags": flags})
    g = _gate(auth_client, pid)
    assert (g["unhandled_warning_count"], g["unresolved_error_count"], g["can_continue"]) == (0, 1, False)
    _seed(uid, [_flag("a:x")])
    auth_client.patch(f"/upload/{uid}/acknowledged-flags", json={"flags": [_flag("a:x")]})
    assert _gate(auth_client, pid)["can_continue"] is True


def test_run_plan_409_names_outstanding_kind(auth_client):
    pid, uid = _setup(auth_client)
    _seed(uid, [_flag("a:x"), _flag("e:age", "ERROR")])
    from tests.helpers import advance_to_phase
    advance_to_phase(pid, "plan")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.ai_analysis_plan = json.dumps({"confirmed": True})
        db.get(Upload, uid).acknowledged_flags = "[]"  # the helper acknowledges warnings; this test needs one outstanding
        db.commit()
    body = {"upload_id": uid, "analyses": [{"template": "descriptive_summary", "parameters": {"value_cols": ["age"]}}]}
    msg = auth_client.post(f"/analyze/run-plan/{pid}", json=body).json()["error"]["message"]
    assert "1 data quality warning" in msg and "1 data quality error" in msg
    auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x"]})
    msg = auth_client.post(f"/analyze/run-plan/{pid}", json=body).json()["error"]["message"]
    assert "warning" not in msg and "error" in msg


# ---- review fixes ----

def _legacy(fid, sev="WARNING"):
    f = _flag(fid, sev)
    del f["id"]
    return f


def test_legacy_flags_without_ids_work_end_to_end(auth_client):
    pid, uid = _setup(auth_client)
    _seed(uid, [_legacy("a:x"), _legacy("b:y"), _legacy("c:z")])
    assert set(_states(auth_client, uid)) == {"a:x", "b:y", "c:z"}
    assert auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x"]}).status_code == 201
    gid = auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["b:y"], "action": "clarify"}).json()["id"]
    from api.models_db import WarningGroup
    from api.routers.warning_groups import mark_group_handled
    with SessionLocal() as db:
        mark_group_handled(db, db.get(Upload, uid), db.get(WarningGroup, gid))
    s = _states(auth_client, uid)
    assert (s["a:x"]["state"], s["b:y"]["state"], s["c:z"]["state"]) == ("handled", "handled", "unhandled")
    assert _gate(auth_client, pid)["unhandled_warning_count"] == 1


def test_cancel_clarify_group_and_conflicts(auth_client):
    _, uid = _setup(auth_client)
    _seed(uid, FLAGS)
    gid = auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["a:x"], "action": "clarify"}).json()["id"]
    r = auth_client.delete(f"/upload/{uid}/warning-groups/{gid}")
    assert r.status_code == 200 and {f["flag_id"]: f["state"] for f in r.json()["flags"]}["a:x"] == "unhandled"
    assert auth_client.get(f"/upload/{uid}/warning-groups").json()["groups"] == []
    from api.models_db import AuditLog
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(action="warning_group_cancelled").count() == 1
    assert auth_client.delete(f"/upload/{uid}/warning-groups/{gid}").status_code == 404
    ack = auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["b:y"]}).json()["id"]
    r = auth_client.delete(f"/upload/{uid}/warning-groups/{ack}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "group_not_cancellable"
    # a clarify group whose steps were applied is not cancellable
    g2 = auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["c:z"], "action": "clarify"}).json()["id"]
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.handoff_steps = json.dumps([{"op": "trim", "columns": ["unit"], "warning_ids": ["c:z"]}])
        db.commit()
    assert auth_client.delete(f"/upload/{uid}/warning-groups/{g2}").status_code == 409


def test_acknowledge_supersedes_unconfirmed_clarify_group(auth_client):
    _, uid = _setup(auth_client)
    _seed(uid, FLAGS)
    auth_client.post(f"/upload/{uid}/warning-groups", json={"flag_ids": ["a:x", "b:y"], "action": "clarify"})
    r = auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x"]})
    assert r.status_code == 201 and r.json()["status"] == "handled"
    s = _states(auth_client, uid)
    assert s["a:x"]["state"] == "handled" and s["b:y"]["state"] == "unhandled"
    assert [x["action"] for x in auth_client.get(f"/upload/{uid}/warning-groups").json()["groups"]] == ["acknowledge"]
    # a handled group still blocks
    assert auth_client.post(f"/upload/{uid}/warnings/acknowledge", json={"flag_ids": ["a:x"]}).status_code == 409


def test_pending_choice_blocks_gating(auth_client):
    pid, uid = _setup(auth_client)
    _seed(uid, [])
    assert _gate(auth_client, pid)["can_continue"] is True
    with SessionLocal() as db:
        db.get(Upload, uid).handoff_status = "pending_choice"
        db.commit()
    g = _gate(auth_client, pid)
    assert g["can_continue"] is False and g["pending_choice"] is True
    from api.models_api import GatingOut
    from api.routers.warning_groups import gating_block_message
    assert "keep your earlier changes or start fresh" in gating_block_message(GatingOut(**g))


def test_error_with_dropped_column_stays_unresolved(auth_client, recheck):
    pid, uid = _setup(auth_client)
    _seed(uid, [_flag("e:age", "ERROR")])
    recheck["gone"].add("e:age")
    assert _gate(auth_client, pid)["unresolved_error_count"] == 0  # column present, rule no longer fires
    with SessionLocal() as db:
        db.get(Upload, uid).handoff_steps = json.dumps([{"op": "drop_column", "columns": ["age"]}])
        db.commit()
    g = _gate(auth_client, pid)
    assert (g["unresolved_error_count"], g["can_continue"]) == (1, False)


def test_error_appearing_only_after_cleaning_blocks(auth_client, monkeypatch):
    import api.cleaning_runtime as cr
    pid, uid = _setup(auth_client)
    _seed(uid, [_flag("a:x")])
    assert _gate(auth_client, pid)["unresolved_error_count"] == 0
    new = _flag("rows:unit", "ERROR")
    monkeypatch.setattr(cr, "recheck_flags", lambda upload: [new])
    with SessionLocal() as db:
        db.get(Upload, uid).handoff_steps = json.dumps([{"op": "trim", "columns": ["unit"]}])
        db.commit()
    g = _gate(auth_client, pid)
    assert (g["unresolved_error_count"], g["can_continue"]) == (1, False)
    assert _states(auth_client, uid)["rows:unit"]["severity"] == "ERROR"


def test_unverifiable_error_stays_blocking(auth_client, monkeypatch):
    import api.cleaning_runtime as cr
    pid, uid = _setup(auth_client)
    _seed(uid, [_flag("e:age", "ERROR")])
    def boom(upload):
        raise RuntimeError("x")
    monkeypatch.setattr(cr, "recheck_flags", boom)
    assert _gate(auth_client, pid)["unresolved_error_count"] == 1
