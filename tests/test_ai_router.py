"""Tests for /ai/chat PHI scrubbing (no real API calls)."""
import pytest
from unittest.mock import patch, MagicMock
import os

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def _mock_openrouter(content="Test response"):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"choices": [{"message": {"content": content}}]}
    return mock


def test_chat_scrubs_phi():
    """Messages with PHI (SSN pattern) get redacted; phi_redacted=True returned."""
    with patch("api.routers.ai.httpx.post", return_value=_mock_openrouter()) as m:
        # Give a valid key so the endpoint doesn't 503
        with patch("api.routers.ai.settings") as s:
            s.openrouter_api_key = "fake-key"
            resp = client.post("/ai/chat", json={
                "project_id": 1,
                "messages": [{"role": "user", "content": "Patient SSN 123-45-6789 has diabetes"}],
            })
    assert resp.status_code == 200
    data = resp.json()
    assert data["phi_redacted"] is True
    assert data["redaction_count"] > 0
    # Confirm the actual API call received scrubbed text, not the raw SSN
    called_messages = m.call_args[1]["json"]["messages"]
    assert "123-45-6789" not in called_messages[0]["content"]
    assert "[REDACTED]" in called_messages[0]["content"]


def test_chat_no_phi():
    """Clean messages pass through without redaction."""
    with patch("api.routers.ai.httpx.post", return_value=_mock_openrouter("Clean answer")):
        with patch("api.routers.ai.settings") as s:
            s.openrouter_api_key = "fake-key"
            resp = client.post("/ai/chat", json={
                "project_id": 1,
                "messages": [{"role": "user", "content": "Explain a run chart"}],
            })
    assert resp.status_code == 200
    data = resp.json()
    assert data["phi_redacted"] is False
    assert data["content"] == "Clean answer"


def test_chat_no_api_key():
    """Returns 503 when OPENROUTER_API_KEY is not configured."""
    with patch("api.routers.ai.settings") as s:
        s.openrouter_api_key = ""
        resp = client.post("/ai/chat", json={
            "project_id": 1,
            "messages": [{"role": "user", "content": "hello"}],
        })
    assert resp.status_code == 503
