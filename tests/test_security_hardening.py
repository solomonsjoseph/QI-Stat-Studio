"""Regression tests for the beta 1 security audit findings."""
import logging
import os

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

import pytest
from fastapi import HTTPException

from api.config import settings
from api.main import _MaskShareTokens
from api.middleware import phi_scrubber
from api.models_api import MentorCommentEditIn, MentorCommentIn
from api.routers import share
from api.settings_registry import REGISTRY, _validate_value


def test_scrub_text_waits_for_the_name_model_instead_of_sending_regex_only_text(monkeypatch):
    seen = {}

    def fake_get_nlp(wait=False):
        seen["wait"] = wait
        return None

    monkeypatch.setattr(phi_scrubber, "_get_nlp", fake_get_nlp)
    phi_scrubber.scrub_text("Mr John Smith fell")
    assert seen["wait"] is True


def test_comment_edit_token_depends_on_the_install_specific_fernet_key(monkeypatch):
    first = share._edit_token(3, 9)
    monkeypatch.setattr(settings, "fernet_key", "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=")
    assert share._edit_token(3, 9) != first


def test_non_ascii_edit_token_is_refused_not_a_server_error():
    with pytest.raises(HTTPException) as exc:
        share._require_edit_token(type("S", (), {"id": 1})(), type("C", (), {"id": 2})(), "tökén")
    assert exc.value.status_code == 403


def test_comment_text_loses_control_characters_that_break_word_export():
    created = MentorCommentIn(author_name="Dr\x00 Rivera", author_email=None, text="Good\x01 work\x0b.")
    assert (created.author_name, created.text) == ("Dr Rivera", "Good work.")
    assert MentorCommentEditIn(edit_token="t", text="a\x00b").text == "ab"


def test_oversized_json_body_is_refused_before_it_is_read(client):
    big = '{"email":"a@b.co","password":"' + "x" * 2_100_000 + '"}'
    response = client.post("/auth/login", content=big, headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_overlong_password_is_rejected(client):
    response = client.post("/auth/register", json={"email": "long@example.com", "password": "p" * 257})
    assert response.status_code == 422


def test_responses_carry_security_headers(client):
    headers = client.get("/health").headers
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_dev_quit_is_admin_only(client):
    client.post("/auth/register", json={"email": "first-admin@example.com", "password": "password123"})
    client.post("/auth/logout")
    client.post("/auth/register", json={"email": "second-user@example.com", "password": "password123"})
    assert client.post("/dev/quit").status_code in (403, 401)


def test_local_api_base_must_be_an_http_url():
    spec = REGISTRY["local_api_base"]
    assert _validate_value(spec, "http://localhost:11434") == "http://localhost:11434"
    with pytest.raises(HTTPException):
        _validate_value(spec, "file:///etc/passwd")


def test_share_tokens_are_masked_in_access_log_lines():
    token = "A" * 43
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:1", "GET", f"/share/view/{token}/comment", "1.1", 200), None)
    _MaskShareTokens().filter(record)
    assert token not in record.getMessage()
    assert "/share/view/[token]/comment" in record.getMessage()
