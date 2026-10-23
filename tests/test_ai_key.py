import os
os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from api.database import SessionLocal
from api.models_db import AppSetting, AuditLog
from tests.test_ai_router import _project_id, _set_openrouter_provider

SECRET = "sk-test-SECRET-1234"


def _status(client):
    r = client.get("/settings/ai-key")
    assert r.status_code == 200
    return r.json()


def test_no_key_status_and_clarify_structured_503(client, monkeypatch):
    _set_openrouter_provider()
    monkeypatch.setattr("api.config.settings.openrouter_api_key", "")
    pid = _project_id(client)
    assert _status(client) == {"configured": False, "source": "none", "last4": None, "provider": "openrouter", "advisor_available": False}
    r = client.post("/ai/chat", json={"project_id": pid, "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503
    d = r.json()["error"]
    assert d["code"] == "advisor_unavailable" and d["key_source"] == "none" and "API_KEY" not in d["message"]


def test_settings_key_overrides_env_masked_and_encrypted(client, monkeypatch):
    _set_openrouter_provider()
    monkeypatch.setattr("api.config.settings.openrouter_api_key", "env-key-ENV9")
    _project_id(client)
    s = _status(client)
    assert (s["source"], s["last4"]) == ("env", "ENV9")

    r = client.put("/settings/ai-key", json={"key": SECRET})
    assert r.status_code == 200
    assert SECRET not in r.text
    s = _status(client)
    assert (s["source"], s["last4"], s["advisor_available"]) == ("settings", "1234", True)
    assert SECRET not in client.get("/settings").text

    from api.routers.ai import _provider_settings
    with SessionLocal() as db:
        assert _provider_settings(db)[1] == SECRET
        raw = " ".join(row.value for row in db.query(AppSetting).all() if row.value)
        assert SECRET not in raw
        assert SECRET not in " ".join(str(a.meta) for a in db.query(AuditLog).all() if hasattr(a, "meta"))

    # clearing falls back to env
    r = client.delete("/settings/ai-key")
    assert r.status_code == 200
    s = _status(client)
    assert (s["source"], s["last4"]) == ("env", "ENV9")


def test_cleared_with_no_env_is_none(client, monkeypatch):
    _set_openrouter_provider()
    monkeypatch.setattr("api.config.settings.openrouter_api_key", "")
    _project_id(client)
    client.put("/settings/ai-key", json={"key": SECRET})
    assert _status(client)["configured"] is True
    client.delete("/settings/ai-key")
    assert _status(client)["configured"] is False


def test_requires_login_and_validates(client):
    assert client.get("/settings/ai-key").status_code in (401, 403)
    _project_id(client)
    assert client.put("/settings/ai-key", json={"key": "x"}).status_code == 422


def test_no_key_manual_path_reaches_results(client, monkeypatch):
    from tests.test_full_journey import FIXTURE
    _set_openrouter_provider()
    monkeypatch.setattr("api.config.settings.openrouter_api_key", "")
    client.post("/auth/register", json={"email": "manual@example.com", "password": "password123"})
    with FIXTURE.open("rb") as fh:
        intake = client.post("/projects/intake", data={"title": "T", "description": "Improve A1c at goal."},
                             files={"file": (FIXTURE.name, fh, "text/csv")})
    assert intake.status_code == 200, intake.text
    pid, upload = intake.json()["project"]["id"], intake.json()["upload"]
    assert client.post(f"/ai/clarify/{pid}", json={"message": "hi"}).status_code == 503
    assert client.post(f"/ai/clarify/{pid}", json={"confirm": True}).status_code == 200
    g = client.post(f"/ai/collection-guidance/{pid}")
    assert g.status_code == 200
    assert client.patch(f"/upload/{upload['id']}/acknowledged-flags", json={"flags": upload["quality_flags"]}).status_code == 200
    # ERRORs are never cleared by acknowledging: simulate a passing re-check on the cleaned data.
    monkeypatch.setattr("api.cleaning_runtime.recheck_flags", lambda upload: [])
    assert client.patch(f"/upload/{upload['id']}/acknowledged-flags", json={"flags": upload["quality_flags"]}).status_code == 200
    analyses = [{"id": "d", "template": "descriptive_summary", "display_name": "d", "question": "q",
                 "rationale": "r", "parameters": {"value_cols": ["a1c_at_goal"]}}]
    assert client.post(f"/ai/recommend-plan/{pid}", json={"message": None}).status_code == 200
    assert client.post(f"/ai/recommend-plan/{pid}", json={"confirm": True, "analyses": analyses}).status_code == 200
    run = client.post(f"/analyze/run-plan/{pid}", json={"upload_id": upload["id"], "analyses": analyses})
    assert run.status_code == 200 and run.json()["failures"] == []
    assert client.post(f"/ai/override-plan/{pid}", json={"instruction": "x"}).status_code == 503
    r = client.post(f"/ai/interpret-results/{pid}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "advisor_unavailable"
    assert client.get(f"/report/project/{pid}/docx").status_code == 200
    assert client.get(f"/report/project/{pid}/pdf").status_code == 200
