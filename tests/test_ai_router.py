"""Focused AI router guardrail tests; OpenRouter is always mocked."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from api.database import SessionLocal
from api.models_db import AIUsageEvent, AppSetting


def _mock_openrouter(content="Test response", status_code=200, text=""):
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text or ("ok" if status_code == 200 else "upstream failed")
    mock.json.return_value = {"choices": [{"message": {"content": content}}]}
    return mock


def _project_id(client):
    response = client.post("/auth/register", json={"email": "owner@example.com", "password": "password123"})
    assert response.status_code == 200, response.text
    response = client.post("/projects", json={"title": "AI project", "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _set_runtime_setting(key, value):
    with SessionLocal() as db:
        db.add(AppSetting(key=key, value=str(value)))
        db.commit()


def _ai_usage_rows():
    with SessionLocal() as db:
        return db.query(AIUsageEvent).order_by(AIUsageEvent.id.asc()).all()


def test_chat_scrubs_phi_and_records_usage(client, monkeypatch):
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.httpx.post", return_value=_mock_openrouter()) as mocked_post:
        response = client.post(
            "/ai/chat",
            json={
                "project_id": project_id,
                "messages": [{"role": "user", "content": "Patient SSN 123-45-6789 has diabetes"}],
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["phi_redacted"] is True
    assert data["redaction_count"] > 0
    payload = mocked_post.call_args.kwargs["json"]
    assert payload["max_tokens"] == 800
    assert "123-45-6789" not in payload["messages"][0]["content"]
    assert "[REDACTED]" in payload["messages"][0]["content"]
    rows = _ai_usage_rows()
    assert len(rows) == 1
    assert rows[0].status == "ok"
    assert rows[0].completion_chars == len("Test response")


def test_chat_uses_runtime_model_when_request_model_omitted(client, monkeypatch):
    project_id = _project_id(client)
    _set_runtime_setting("openrouter_model", "runtime/model")
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.httpx.post", return_value=_mock_openrouter("Clean answer")) as mocked_post:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "Explain a run chart"}]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "Clean answer"
    assert mocked_post.call_args.kwargs["json"]["model"] == "runtime/model"


def test_chat_request_model_overrides_runtime_model(client, monkeypatch):
    project_id = _project_id(client)
    _set_runtime_setting("openrouter_model", "runtime/model")
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.httpx.post", return_value=_mock_openrouter()) as mocked_post:
        response = client.post(
            "/ai/chat",
            json={
                "project_id": project_id,
                "model": "request/model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200, response.text
    assert mocked_post.call_args.kwargs["json"]["model"] == "request/model"


def test_chat_rate_limit_uses_db_events(client, monkeypatch):
    project_id = _project_id(client)
    _set_runtime_setting("ai_rate_limit_per_hour", "1")
    with SessionLocal() as db:
        db.add(
            AIUsageEvent(
                user_id=1,
                project_id=project_id,
                model="runtime/model",
                prompt_chars=1,
                completion_chars=1,
                status="ok",
                created_at=datetime.utcnow() - timedelta(minutes=5),
            )
        )
        db.commit()
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.httpx.post") as mocked_post:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 429
    assert mocked_post.call_count == 0


def test_chat_retries_429_and_5xx_then_succeeds(client, monkeypatch):
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    responses = [_mock_openrouter(status_code=500), _mock_openrouter(status_code=429), _mock_openrouter("Recovered")]
    with patch("api.routers.ai.time.sleep") as mocked_sleep:
        with patch("api.routers.ai.httpx.post", side_effect=responses) as mocked_post:
            response = client.post(
                "/ai/chat",
                json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
            )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "Recovered"
    assert mocked_post.call_count == 3
    assert mocked_sleep.call_count == 2


def test_chat_rejects_user_content_over_4000_chars(client, monkeypatch):
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.httpx.post") as mocked_post:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "x" * 4001}]},
        )

    assert response.status_code == 400
    assert mocked_post.call_count == 0


def test_chat_no_api_key_records_not_configured_usage(client, monkeypatch):
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "")

    response = client.post(
        "/ai/chat",
        json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 503
    rows = _ai_usage_rows()
    assert len(rows) == 1
    assert rows[0].status == "not_configured"


def test_chat_transport_exception_records_error_usage_and_returns_safe_502(client, monkeypatch):
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.httpx.post", side_effect=RuntimeError("MRN 123456 secret@example.com upstream exploded")):
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == "AI service unavailable"
    assert "MRN 123456" not in response.text
    assert "secret@example.com" not in response.text
    rows = _ai_usage_rows()
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert rows[0].completion_chars == 0


def test_chat_upstream_error_body_is_not_returned(client, monkeypatch):
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")
    upstream = _mock_openrouter(status_code=500, text="upstream leaked MRN 123456 secret@example.com")

    with patch("api.routers.ai.httpx.post", return_value=upstream):
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == "AI service unavailable"
    assert "MRN 123456" not in response.text
    assert "secret@example.com" not in response.text
    rows = _ai_usage_rows()
    assert len(rows) == 1
    assert rows[0].status == "error"
