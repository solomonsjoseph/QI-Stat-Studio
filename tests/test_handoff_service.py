import hashlib
import json

import pytest

from api.database import SessionLocal
from api.handoff import extract_steps
from api.handoff_service import ensure_handoff
from api.models_db import Project, Upload
from api.routers import ai as ai_router

CSV = b"encounter_id,value,status\n1,10,Yes \n2,20,No\n3,30,yes\n4,500,No\n5,12,Yes\n6,11,No\n7,13,No\n8,14,Yes\n"


def _provider(monkeypatch, provider, key):
    monkeypatch.setattr(ai_router, "_provider_settings", lambda db, user_id: (provider, key, None, "m"))


def _create(client, content=CSV):
    r = client.post(
        "/projects/intake",
        data={"title": "Falls", "description": "d"},
        files={"file": ("data.csv", content, "text/csv"),
               "dictionary": ("dict.txt", b"value: measured outcome", "text/plain")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _upload(upload_id):
    with SessionLocal() as db:
        u = db.get(Upload, upload_id)
        db.expunge(u)
        return u


def test_skeleton_stored_without_key(auth_client, monkeypatch):
    _provider(monkeypatch, "openrouter", None)
    called = []
    monkeypatch.setattr(ai_router, "_llm_completion_nonempty", lambda *a, **k: called.append(1))
    body = _create(auth_client)
    u = _upload(body["upload"]["id"])
    assert not called
    assert u.handoff_status == "current" and u.handoff_revision == 1 and u.handoff_steps == "[]"
    assert "## QI Stat Advisor summary" not in u.handoff_md
    assert extract_steps(u.handoff_md) == []
    assert json.loads(u.handoff_revisions)[0]["kind"] == "created"
    assert u.handoff_updated_at is not None
    assert u.dictionary_checksum_sha256 == hashlib.sha256(b"value: measured outcome").hexdigest()
    assert "Examples:" in u.handoff_md  # outlier / whitespace examples


def test_stub_summary_inserted_above_warnings(auth_client, monkeypatch):
    _provider(monkeypatch, "stub", "stub")
    body = _create(auth_client)
    u = _upload(body["upload"]["id"])
    md = u.handoff_md
    assert md.index("## QI Stat Advisor summary") < md.index("## Quality warnings")
    assert extract_steps(md) == []


def test_ai_failure_falls_back(auth_client, monkeypatch):
    _provider(monkeypatch, "stub", "stub")

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(ai_router, "_llm_completion_nonempty", boom)
    body = _create(auth_client)
    u = _upload(body["upload"]["id"])
    assert u.handoff_status == "current"
    assert "## QI Stat Advisor summary" not in u.handoff_md


def test_scrub_text_applied_to_sent_text(auth_client, monkeypatch):
    _provider(monkeypatch, "stub", "stub")
    from api import handoff_service

    seen = {}

    def fake_scrub(text, *a, **k):
        seen["in"] = text
        return "SCRUBBED-DOC", 2

    sent = []
    real = ai_router._llm_completion_nonempty

    def spy(provider, key, base, model, messages, **k):
        sent.append(messages)
        return real(provider, key, base, model, messages, **k)

    monkeypatch.setattr(handoff_service, "scrub_text", fake_scrub)
    monkeypatch.setattr(ai_router, "_llm_completion_nonempty", spy)
    _create(auth_client)
    assert "# Handoff: Falls" in seen["in"]
    assert "SCRUBBED-DOC" in sent[0][0]["content"] and "<untrusted_data>" in sent[0][0]["content"]
    assert "Falls" not in sent[0][0]["content"]


def test_lazy_ensure_for_old_upload(auth_client, monkeypatch):
    _provider(monkeypatch, "openrouter", None)
    body = _create(auth_client)
    uid = body["upload"]["id"]
    with SessionLocal() as db:
        u = db.get(Upload, uid)
        u.handoff_md, u.handoff_status, u.handoff_revision = None, "none", 0
        db.commit()
        project = db.get(Project, u.project_id)
        ensure_handoff(db, project, u)
    u = _upload(uid)
    assert u.handoff_status == "current" and u.handoff_revision == 1
    assert "# Handoff: Falls" in u.handoff_md


def test_replace_creates_new_handoff(auth_client, monkeypatch):
    _provider(monkeypatch, "openrouter", None)
    body = _create(auth_client)
    pid, uid = body["project"]["id"], body["upload"]["id"]
    r = auth_client.post(f"/upload/{pid}/replace/{uid}",
                         files={"file": ("new.csv", CSV + b"9,15,No\n", "text/csv")})
    assert r.status_code == 200, r.text
    new = _upload(r.json()["id"])
    assert new.id != uid and new.handoff_status == "current" and "new.csv" in new.handoff_md


def test_flag_examples_survive_legacy_and_bad_flags():
    import pandas as pd

    from api.handoff_service import flag_examples

    df = pd.DataFrame({"sex": ["M ", "F"]})
    flags = [{"col": "sex", "rule": "whitespace_padding"}, {"col": ["bad"], "rule": "outlier_count"}, {"rule": "x"}]
    assert flag_examples(df, flags) == {"whitespace_padding:sex": ["'M '"]}
