from api.middleware import phi_scrubber
from api.middleware.phi_scrubber import scrub_text


def _create_project(client) -> int:
    response = client.post("/auth/register", json={"email": "owner@example.com", "password": "password123"})
    assert response.status_code == 200, response.text
    response = client.post("/projects", json={"title": "AI project", "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_redacts_person_name_when_ner_available():
    result, count = scrub_text("Patient John Smith was admitted")
    if phi_scrubber._nlp is None:
        assert result == "Patient John Smith was admitted"
        assert count == 0
    else:
        assert "John Smith" not in result
        assert count >= 1


def test_redacts_mrn_pattern():
    result, count = scrub_text("MRN: 1234567")
    assert "1234567" not in result
    assert count >= 1


def test_redacts_ssn():
    result, count = scrub_text("SSN 123-45-6789")
    assert "123-45-6789" not in result
    assert count >= 1


def test_redacts_email():
    result, count = scrub_text("Contact patient@hospital.org")
    assert "patient@hospital.org" not in result
    assert count >= 1


def test_clean_text_unchanged():
    text = "Mean A1c decreased from 8.2 to 7.4 (p=0.03)"
    result, count = scrub_text(text)
    assert count == 0
    assert result == text


def test_regex_fallback_redacts_mrn_email_and_dates_when_spacy_missing(monkeypatch):
    monkeypatch.setattr(phi_scrubber, "_nlp", None)

    result, count = scrub_text("MRN 1234567 email a@example.org visit 02/03/2024 followup 2024-03-04")

    assert "1234567" not in result
    assert "a@example.org" not in result
    assert "02/03/2024" not in result
    assert "2024-03-04" not in result
    assert count == 4


def test_regex_fallback_redacts_street_addresses(monkeypatch):
    monkeypatch.setattr(phi_scrubber, "_nlp", None)

    result, count = scrub_text("Patient lives at 123 Main Street and attends clinic")

    assert "123 Main Street" not in result
    assert "[REDACTED]" in result
    assert count == 1


def test_ai_chat_scrubs_phi_from_system_messages_before_outbound_call(client, monkeypatch):
    project_id = _create_project(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")
    captured = {}

    class FakeMessage:
        content = "ok"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    def fake_llm_completion(provider, api_key, api_base, model, messages):
        captured["messages"] = messages
        return FakeResponse()

    monkeypatch.setattr("api.routers.ai._llm_completion", fake_llm_completion)

    response = client.post(
        "/ai/chat",
        json={
            "project_id": project_id,
            "messages": [
                {"role": "system", "content": "Patient John Smith, SSN 123-45-6789"},
                {"role": "user", "content": "hi"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    system_message = captured["messages"][0]
    assert system_message["role"] == "system"
    assert "123-45-6789" not in system_message["content"]
    assert response.json()["redaction_count"] >= 1
