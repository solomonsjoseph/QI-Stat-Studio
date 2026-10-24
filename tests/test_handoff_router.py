import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from api.database import SessionLocal
from api.main import app
from api.models_db import AuditLog, Upload

CSV = b"encounter_id,age,unit\n1,10,mg\n2,,MG\n3,30,mg\n"
DICT = ("dict.txt", b"encounter_id: id. age: years. unit: unit.", "text/plain")


def _setup(client, name="d.csv"):
    pid = client.post("/projects", json={"title": "QI", "description": "d"}).json()["id"]
    r = client.post(f"/upload/{pid}", files={"file": (name, CSV, "text/csv"), "dictionary": DICT})
    assert r.status_code == 200, r.text
    return pid, r.json()["upload_id"]


def _mark(uid, status, replaced_at=None, rev=2):
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.handoff_status = status
        u.handoff_md = "# Handoff\nbody"
        u.handoff_steps = json.dumps([{"op": "note", "note": "x"}])
        u.handoff_revision = rev
        u.handoff_replaced_at = replaced_at
        u.handoff_revisions = json.dumps([
            {"revision": i + 1, "created_at": "2026-10-01T00:00:00Z", "actor": "user", "kind": "apply",
             "summary": "s%d" % i, "steps_snapshot": [{"op": "note"}]} for i in range(rev)])
        db.commit()


def _other_user():
    c = TestClient(app)
    r = c.post("/auth/register", json={"email": "other@example.com", "password": "password123"})
    assert r.status_code == 200, r.text
    return c


def test_owner_read_and_ensure_on_old_upload(auth_client):
    pid, uid = _setup(auth_client)
    with SessionLocal() as db:  # simulate an old upload with no handoff
        u = db.get(Upload, uid)
        u.handoff_status, u.handoff_md = "none", None
        db.commit()
    r = auth_client.get(f"/upload/{uid}/handoff")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "current" and body["markdown"] and body["read_only"] is False
    assert body["revision"] == 1 and body["change_log"][0]["kind"] == "created"
    revs = auth_client.get(f"/upload/{uid}/handoff/revisions").json()
    assert [x["revision"] for x in revs["revisions"]] == [1]


def test_mentor_read_only(auth_client):
    pid, uid = _setup(auth_client)
    _mark(uid, "current")
    token = auth_client.post(f"/share/{pid}/create", json={}).json()["token"]
    anon = TestClient(app)
    r = anon.get(f"/share/{token}/handoff")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["read_only"] is True and b["steps"] == [] and b["markdown"] and len(b["change_log"]) == 2
    assert "steps_snapshot" not in json.dumps(b)
    assert anon.get("/share/nope/handoff").status_code == 404
    for call in (anon.put, anon.post, anon.patch, anon.delete):
        assert call(f"/share/{token}/handoff").status_code in (404, 405)
    assert anon.delete(f"/upload/{uid}/handoff").status_code == 401
    auth_client.post(f"/share/{pid}/revoke", json={"token": token})
    assert anon.get(f"/share/{token}/handoff").status_code == 404


def test_history_order_open_and_delete_keeps_log(auth_client):
    pid, old = _setup(auth_client, "old.csv")
    _, mid = _setup(auth_client, "x.csv")  # different project, must not appear
    now = datetime.utcnow()
    with SessionLocal() as db:
        db.get(Upload, mid).project_id = pid
        db.commit()
    _mark(old, "replaced", now - timedelta(days=2))
    _mark(mid, "replaced", now - timedelta(days=1))
    items = auth_client.get(f"/projects/{pid}/handoff-history").json()["items"]
    assert [i["upload_id"] for i in items] == [mid, old]
    assert items[0]["change_log_entries"] == 2 and items[0]["file_name"] == "x.csv"
    opened = auth_client.get(f"/upload/{old}/handoff").json()
    assert opened["read_only"] is True and opened["status"] == "replaced"

    assert auth_client.delete(f"/upload/{old}/handoff").json() == {"ok": True}
    after = auth_client.get(f"/upload/{old}/handoff").json()
    assert after["status"] == "deleted" and after["markdown"] is None and after["steps"] == []
    assert len(after["change_log"]) == 2
    with SessionLocal() as db:
        assert "steps_snapshot" not in db.get(Upload, old).handoff_revisions
        assert db.query(AuditLog).filter(AuditLog.action == "handoff_deleted").count() == 1
    items = auth_client.get(f"/projects/{pid}/handoff-history").json()["items"]
    assert {i["upload_id"]: i["status"] for i in items} == {mid: "replaced", old: "deleted"}
    assert auth_client.delete(f"/upload/{old}/handoff").status_code == 409


def test_delete_current_rejected(auth_client):
    pid, uid = _setup(auth_client)
    r = auth_client.delete(f"/upload/{uid}/handoff")
    assert r.status_code == 409 and r.json()["error"]["code"] == "handoff_is_current"
    assert auth_client.get(f"/upload/{uid}/handoff").json()["markdown"]


def test_cross_user_denied(auth_client):
    pid, uid = _setup(auth_client)
    _mark(uid, "replaced", datetime.utcnow())
    other = _other_user()
    assert other.get(f"/upload/{uid}/handoff").status_code == 403
    assert other.get(f"/upload/{uid}/handoff/revisions").status_code == 403
    assert other.get(f"/projects/{pid}/handoff-history").status_code == 403
    assert other.delete(f"/upload/{uid}/handoff").status_code == 403
    assert other.get("/upload/9999/handoff").status_code == 404
    assert other.delete(f"/admin/upload/{uid}/handoff-log").status_code == 403


def test_admin_purge_only_deleted(auth_client):  # first registered user is admin
    pid, uid = _setup(auth_client)
    _mark(uid, "replaced", datetime.utcnow())
    assert auth_client.delete(f"/admin/upload/{uid}/handoff-log").status_code == 409
    auth_client.delete(f"/upload/{uid}/handoff")
    assert auth_client.delete(f"/admin/upload/{uid}/handoff-log").json() == {"ok": True}
    assert auth_client.get(f"/upload/{uid}/handoff").json()["change_log"] == []
