"""The model list comes from the provider with the caller's key. Nothing is hardcoded."""
import logging
import os

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

import httpx
import pytest
from fastapi import HTTPException

from api import model_catalog
from api.database import SessionLocal
from api.routers.ai import _provider_settings

PAYLOAD = {"data": [
    {"id": "vendor/alpha", "name": "Vendor: Alpha", "context_length": 200000,
     "architecture": {"output_modalities": ["text"]}, "pricing": {"prompt": "0.000003", "completion": "0.000015"},
     "supported_parameters": ["max_tokens", "reasoning"]},
    {"id": "vendor/alpha:batch", "name": "Alpha batch", "architecture": {"output_modalities": ["text"]}, "pricing": {}},
    {"id": "vendor/painter", "name": "Painter", "architecture": {"output_modalities": ["image"]}, "pricing": {}},
]}


@pytest.fixture(autouse=True)
def _clean_cache():
    model_catalog._cache.clear()
    yield
    model_catalog._cache.clear()


def _stub_get(monkeypatch, payload=PAYLOAD, calls=None):
    def fake(url, headers):
        if calls is not None:
            calls.append((url, headers))
        return payload
    monkeypatch.setattr(model_catalog, "_get", fake)


def test_openrouter_list_keeps_text_models_and_drops_batch_and_image_variants(monkeypatch):
    _stub_get(monkeypatch)
    models, source = model_catalog.list_models("openrouter", "k1", None)
    assert source == "live"
    assert [m.id for m in models] == ["vendor/alpha"]
    assert models[0].prompt_price_per_million == 3.0
    assert models[0].reasoning is True


def test_a_key_selects_the_account_specific_list_and_is_sent_as_a_bearer_token(monkeypatch):
    calls = []
    _stub_get(monkeypatch, calls=calls)
    model_catalog.list_models("openrouter", "secret-key", None)
    model_catalog.list_models("openrouter", None, None)
    assert calls[0][0].endswith("/models/user") and calls[0][1] == {"Authorization": "Bearer secret-key"}
    assert calls[1][0].endswith("/models") and calls[1][1] == {}


def test_list_is_cached_until_refresh_is_asked_for(monkeypatch):
    calls = []
    _stub_get(monkeypatch, calls=calls)
    model_catalog.list_models("openrouter", "k", None)
    assert model_catalog.list_models("openrouter", "k", None)[1] == "cache"
    assert model_catalog.list_models("openrouter", "k", None, refresh=True)[1] == "live"
    assert len(calls) == 2


def test_a_rejected_key_gives_a_clear_error_and_the_log_has_no_provider_text(monkeypatch):
    def reject(url, headers):
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("provider said: key sk-leak is bad", request=request, response=httpx.Response(401, request=request))
    monkeypatch.setattr(model_catalog, "_get", reject)
    # Own handler: other tests in the suite reconfigure logging, so caplog can miss this logger.
    seen = []
    handler = logging.Handler()
    handler.emit = lambda record: seen.append(record.getMessage())
    log = model_catalog.logger
    log.addHandler(handler)
    log.disabled, old_level = False, log.level
    log.setLevel(logging.WARNING)
    try:
        with pytest.raises(HTTPException) as exc:
            model_catalog.list_models("openrouter", "bad", None)
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
    assert exc.value.detail["code"] == "models_key_rejected"
    assert seen == ["model_list_failed provider=openrouter status=401 error_type=HTTPStatusError"]
    assert "sk-leak" not in seen[0] and "sk-leak" not in exc.value.detail["message"]


def test_providers_that_need_a_key_ask_for_it_before_calling_out(monkeypatch):
    _stub_get(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        model_catalog.list_models("openai", None, None)
    assert exc.value.detail["code"] == "models_need_key"


def test_gemini_and_openai_lists_are_parsed(monkeypatch):
    _stub_get(monkeypatch, {"models": [{"name": "models/g-1", "displayName": "G One", "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000},
                                       {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]})
    assert [m.id for m in model_catalog.list_models("gemini", "k", None)[0]] == ["g-1"]
    _stub_get(monkeypatch, {"data": [{"id": "gpt-x"}, {"id": "text-embedding-3"}, {"id": "gpt-x-realtime"}]})
    assert [m.id for m in model_catalog.list_models("openai", "k", None)[0]] == ["gpt-x"]


def test_endpoint_lists_models_and_a_users_choice_is_theirs_alone(client, monkeypatch):
    _stub_get(monkeypatch)
    client.post("/auth/register", json={"email": "m1@example.com", "password": "password123"})
    listing = client.get("/settings/ai-models")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["chosen_by"] == "default" and body["current_listed"] is False
    assert client.put("/settings/ai-model", json={"model": "vendor/alpha"}).json()["chosen_by"] == "you"
    again = client.get("/settings/ai-models").json()
    assert again["current_model"] == "vendor/alpha" and again["current_listed"] is True
    with SessionLocal() as db:
        user_id = db.execute(__import__("sqlalchemy").text("select id from users where email='m1@example.com'")).scalar()
        assert _provider_settings(db, user_id)[3] == "vendor/alpha"
        assert _provider_settings(db, None)[3] != "vendor/alpha"  # nobody else is affected
    assert client.delete("/settings/ai-model").json()["chosen_by"] == "default"


def test_invalid_model_id_is_refused(client):
    client.post("/auth/register", json={"email": "m2@example.com", "password": "password123"})
    assert client.put("/settings/ai-model", json={"model": "bad model; drop"}).status_code == 400
