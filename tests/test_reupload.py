import json

from api.database import SessionLocal
from api.models_db import Project, Upload, WarningGroup

CSV = b"encounter_id,value\n1,10\n2,20\n3,30\n4,40\n"
CSV2 = b"encounter_id,value\n1,11\n2,21\n3,31\n4,41\n5,51\n"
DICT = ("dict.txt", b"encounter_id: id. value: measured outcome.", "text/plain")
DICT2 = ("dict.txt", b"encounter_id: id. value: a different description.", "text/plain")


def _setup(client):
    pid = client.post("/projects", json={"title": "QI", "description": "d"}).json()["id"]
    r = client.post(f"/upload/{pid}", files={"file": ("d.csv", CSV, "text/csv"), "dictionary": DICT})
    assert r.status_code == 200, r.text
    return pid, r.json()["upload_id"]


def _replace(client, pid, uid, csv=CSV, dic=DICT):
    return client.post(f"/upload/{pid}/replace/{uid}", files={"file": ("d.csv", csv, "text/csv"), "dictionary": dic})


def _work(uid):
    """Give the active upload a step, a revision, a group and an acknowledgement."""
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.handoff_steps = json.dumps([{"op": "drop_duplicates", "note": "checked"}])
        u.handoff_revision = 3
        u.acknowledged_flags = json.dumps([{"id": "a:x"}])
        db.add(WarningGroup(project_id=u.project_id, upload_id=uid, flag_ids='["a:x"]', action="acknowledge", status="handled"))
        p = db.get(Project, u.project_id)
        p.ai_analysis_plan = json.dumps({"x": 1})
        from api.staleness import compute_inputs_fingerprint
        p.inputs_fingerprint = compute_inputs_fingerprint(p, u)
        db.commit()


def _get(model, i):
    with SessionLocal() as db:
        o = db.get(model, i)
        db.expunge(o)
        return o


def _plan_stale(pid):
    return json.loads(_get(Project, pid).ai_analysis_plan).get("stale", False)


def test_different_file_starts_fresh_and_links_old(auth_client):
    pid, uid = _setup(auth_client)
    _work(uid)
    r = _replace(auth_client, pid, uid, CSV2)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["same_as_previous"], b["started_fresh"], b["choice_required"]) == (False, True, False)
    new, old = _get(Upload, b["id"]), _get(Upload, uid)
    assert new.handoff_status == "current" and new.handoff_steps == "[]" and new.handoff_source_upload_id == uid
    assert old.handoff_status == "replaced" and old.handoff_replaced_at and old.status == "replaced"
    assert old.handoff_steps != "[]" and old.encrypted_path
    assert _plan_stale(pid)
    with SessionLocal() as db:
        assert db.query(WarningGroup).filter_by(upload_id=uid).count() == 1  # stays with old upload


def test_different_dictionary_is_not_same(auth_client):
    pid, uid = _setup(auth_client)
    b = _replace(auth_client, pid, uid, CSV, DICT2).json()
    assert b["started_fresh"] and not b["same_as_previous"]


def test_identical_keep_carries_work_and_plan_not_stale(auth_client):
    pid, uid = _setup(auth_client)
    _work(uid)
    b = _replace(auth_client, pid, uid).json()
    assert (b["same_as_previous"], b["started_fresh"], b["choice_required"]) == (True, False, True)
    nid = b["id"]
    assert _get(Upload, nid).handoff_status == "pending_choice"
    assert _get(Upload, nid).status == "active" and _get(Upload, uid).status == "replaced"
    assert not _plan_stale(pid)

    r = auth_client.post(f"/upload/{nid}/reupload-choice", json={"choice": "keep"})
    assert r.status_code == 200, r.text
    h = r.json()["handoff"]
    assert h["status"] == "current" and h["revision"] == 4 and len(h["steps"]) == 1
    assert h["change_log"][-1]["kind"] == "keep_from_previous" and h["change_log"][-1]["revision"] == 4
    new = _get(Upload, nid)
    assert json.loads(new.acknowledged_flags) == [{"id": "a:x"}]
    with SessionLocal() as db:
        assert db.query(WarningGroup).filter_by(upload_id=nid).count() == 1
        assert db.query(WarningGroup).filter_by(upload_id=uid).count() == 0
    assert _get(Upload, uid).handoff_status == "replaced"
    assert not _plan_stale(pid)


def test_identical_fresh_new_handoff_old_in_history(auth_client):
    pid, uid = _setup(auth_client)
    _work(uid)
    nid = _replace(auth_client, pid, uid).json()["id"]
    r = auth_client.post(f"/upload/{nid}/reupload-choice", json={"choice": "fresh"})
    assert r.status_code == 200, r.text
    h = r.json()["handoff"]
    assert h["status"] == "current" and h["revision"] == 1 and h["steps"] == []
    new, old = _get(Upload, nid), _get(Upload, uid)
    assert new.handoff_source_upload_id == uid and old.handoff_status == "replaced"
    assert old.handoff_steps != "[]"
    with SessionLocal() as db:
        assert db.query(WarningGroup).filter_by(upload_id=uid).count() == 1
        assert db.query(WarningGroup).filter_by(upload_id=nid).count() == 0
    assert _plan_stale(pid)  # old had steps, fresh does not


def test_double_choice_and_no_pending(auth_client):
    pid, uid = _setup(auth_client)
    r = auth_client.post(f"/upload/{uid}/reupload-choice", json={"choice": "keep"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_choice_pending"
    nid = _replace(auth_client, pid, uid).json()["id"]
    assert auth_client.post(f"/upload/{nid}/reupload-choice", json={"choice": "keep"}).status_code == 200
    rev = _get(Upload, nid).handoff_revision
    r = auth_client.post(f"/upload/{nid}/reupload-choice", json={"choice": "fresh"})
    assert r.status_code == 409
    assert _get(Upload, nid).handoff_revision == rev


def test_unresolved_pending_keeps_one_active_upload(auth_client):
    pid, uid = _setup(auth_client)
    nid = _replace(auth_client, pid, uid).json()["id"]
    listed = auth_client.get(f"/upload/project/{pid}").json()
    assert [u["id"] for u in listed] == [nid]


def test_phi_gate_still_enforced(auth_client):
    pid, uid = _setup(auth_client)
    r = _replace(auth_client, pid, uid, b"patient_name,mrn,val\nJane Doe,100234,10\n")
    assert r.status_code == 422
    assert _get(Upload, uid).status == "active" and _get(Upload, uid).handoff_status == "current"


def test_ownership(client):
    client.post("/auth/register", json={"email": "owner@example.com", "password": "password123"})
    pid, uid = _setup(client)
    nid = _replace(client, pid, uid).json()["id"]
    client.post("/auth/logout")
    assert client.post("/auth/register", json={"email": "other@example.com", "password": "password123"}).status_code == 200
    assert client.post(f"/upload/{nid}/reupload-choice", json={"choice": "keep"}).status_code in (403, 404)
    assert _get(Upload, nid).handoff_status == "pending_choice"


def _set_steps(uid, steps):
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.handoff_steps = json.dumps(steps)
        db.commit()


def test_keep_rebuilds_profile_from_cleaned_frame(auth_client):
    pid, uid = _setup(auth_client)
    _work(uid)
    _set_steps(uid, [{"op": "drop_column", "column": "value"}])
    nid = _replace(auth_client, pid, uid).json()["id"]
    r = auth_client.post(f"/upload/{nid}/reupload-choice", json={"choice": "keep"})
    assert r.status_code == 200, r.text
    prof = json.loads(_get(Upload, nid).dataset_profile)
    assert [c["name"] for c in prof["columns"]] == ["encounter_id"]
    assert prof["row_count"] == 4


def test_keep_with_unappliable_steps_is_409_and_stays_pending(auth_client):
    pid, uid = _setup(auth_client)
    _work(uid)
    _set_steps(uid, [{"op": "drop_column", "column": "no_such_column"}])
    nid = _replace(auth_client, pid, uid).json()["id"]
    r = auth_client.post(f"/upload/{nid}/reupload-choice", json={"choice": "keep"})
    assert r.status_code == 409, r.text
    new = _get(Upload, nid)
    assert new.handoff_status == "pending_choice"
    with SessionLocal() as db:
        assert db.query(WarningGroup).filter_by(upload_id=uid).count() == 1
        assert db.query(WarningGroup).filter_by(upload_id=nid).count() == 0
