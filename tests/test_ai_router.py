"""Focused AI router guardrail tests; the outbound LLM call (litellm.completion) is always mocked."""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from api.database import SessionLocal
from api.models_db import AIUsageEvent, AppSetting, Project, Upload


def _mock_completion(content="Test response"):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _project_id(client):
    response = client.post("/auth/register", json={"email": "owner@example.com", "password": "password123"})
    assert response.status_code == 200, response.text
    response = client.post("/projects", json={"title": "AI project", "description": "desc"})
    assert response.status_code == 200, response.text
    pid = response.json()["id"]
    from tests.helpers import advance_to_phase
    advance_to_phase(pid, "plan")
    return pid


def _set_runtime_setting(key, value):
    with SessionLocal() as db:
        db.add(AppSetting(key=key, value=str(value)))
        db.commit()


def _set_openrouter_provider():
    _set_runtime_setting("ai_provider", "openrouter")


def _ai_usage_rows():
    with SessionLocal() as db:
        return db.query(AIUsageEvent).order_by(AIUsageEvent.id.asc()).all()


def test_chat_scrubs_phi_and_records_usage(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion()) as mocked_completion:
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
    kwargs = mocked_completion.call_args.kwargs
    assert kwargs["max_tokens"] == 800
    assert "123-45-6789" not in kwargs["messages"][0]["content"]
    assert "[REDACTED]" in kwargs["messages"][0]["content"]
    rows = _ai_usage_rows()
    assert len(rows) == 1
    assert rows[0].status == "ok"
    assert rows[0].completion_chars == len("Test response")


def test_chat_scrubs_phi_from_non_content_message_fields(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion()) as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={
                "project_id": project_id,
                "messages": [
                    {
                        "role": "user",
                        "content": "clean text",
                        "name": "Contact SSN 123-45-6789 for follow-up",
                    }
                ],
            },
        )

    assert response.status_code == 200, response.text
    sent_message = mocked_completion.call_args.kwargs["messages"][0]
    assert sent_message["content"] == "clean text"
    assert "123-45-6789" not in sent_message["name"]
    assert "[REDACTED]" in sent_message["name"]


def test_chat_uses_runtime_model_when_request_model_omitted(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    _set_runtime_setting("openrouter_model", "runtime/model")
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion("Clean answer")) as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "Explain a run chart"}]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "Clean answer"
    assert mocked_completion.call_args.kwargs["model"] == "openrouter/runtime/model"


def test_chat_request_model_overrides_runtime_model(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    _set_runtime_setting("openrouter_model", "runtime/model")
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion()) as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={
                "project_id": project_id,
                "model": "request/model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200, response.text
    assert mocked_completion.call_args.kwargs["model"] == "openrouter/request/model"


def test_chat_uses_openai_provider_when_configured(client, monkeypatch):
    project_id = _project_id(client)
    _set_runtime_setting("ai_provider", "openai")
    _set_runtime_setting("openai_model", "gpt-4o-mini")
    monkeypatch.setattr("api.routers.ai.settings.openai_api_key", "sk-fake-openai")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion("From OpenAI")) as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "From OpenAI"
    kwargs = mocked_completion.call_args.kwargs
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["api_key"] == "sk-fake-openai"
    assert "api_base" not in kwargs


def test_chat_uses_local_provider_without_requiring_api_key(client, monkeypatch):
    project_id = _project_id(client)
    _set_runtime_setting("ai_provider", "local")
    _set_runtime_setting("local_model", "llama3.1")
    _set_runtime_setting("local_api_base", "http://localhost:11434")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion("From local model")) as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "From local model"
    kwargs = mocked_completion.call_args.kwargs
    assert kwargs["model"] == "ollama_chat/llama3.1"
    assert kwargs["api_base"] == "http://localhost:11434"
    assert "api_key" not in kwargs


def test_chat_rate_limit_uses_db_events(client, monkeypatch):
    _set_openrouter_provider()
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

    with patch("api.routers.ai.litellm.completion") as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 429
    assert mocked_completion.call_count == 0


def test_chat_requests_retries_and_timeout_from_litellm(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion("Recovered")) as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "Recovered"
    kwargs = mocked_completion.call_args.kwargs
    assert kwargs["num_retries"] == 2
    assert kwargs["timeout"] == 30


def test_chat_rejects_user_content_over_4000_chars(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion") as mocked_completion:
        response = client.post(
            "/ai/chat",
            json={"project_id": project_id, "messages": [{"role": "user", "content": "x" * 4001}]},
        )

    assert response.status_code == 400
    assert mocked_completion.call_count == 0


def test_chat_no_api_key_records_not_configured_usage(client, monkeypatch):
    _set_openrouter_provider()
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
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", side_effect=RuntimeError("MRN 123456 secret@example.com upstream exploded")):
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

    with patch(
        "api.routers.ai.litellm.completion",
        side_effect=RuntimeError("upstream leaked MRN 123456 secret@example.com"),
    ):
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


def test_scrub_preview_redacts_without_calling_the_llm(client, monkeypatch):
    _project_id(client)

    with patch("api.routers.ai.litellm.completion") as mocked_completion:
        response = client.post("/ai/scrub-preview", json={"text": "Call me, MRN 1234567"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["redacted"] is True
    assert body["count"] >= 1
    assert "1234567" not in body["text"]
    assert mocked_completion.call_count == 0


def test_scrub_preview_leaves_clean_text_unchanged(client):
    _project_id(client)

    response = client.post("/ai/scrub-preview", json={"text": "Mean A1c decreased from 8.2 to 7.4"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["redacted"] is False
    assert body["count"] == 0
    assert body["text"] == "Mean A1c decreased from 8.2 to 7.4"


def test_scrub_preview_preserves_dates_matching_ai_clarify_behavior(client):
    """/ai/scrub-preview must not flag dates as redacted: /ai/clarify's actual send
    uses scrub_text(..., redact_dates=False) since an intervention start date is
    operationally relevant QI content, not PHI. If preview disagreed, the frontend
    would show a false "redacted" warning and force a spurious extra confirm click
    on any message mentioning a date."""
    _project_id(client)

    response = client.post("/ai/scrub-preview", json={"text": "The protocol began in January 2025."})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["redacted"] is False
    assert body["count"] == 0
    assert body["text"] == "The protocol began in January 2025."


def _clarify_reply(**overrides):
    payload = {
        "message": "Here's what I understood about your project...",
        "reasoning": "Reviewing the description and dataset schema.",
        "suggested_title": "Fall-Risk Screening Impact on Falls Rate, Unit 3W",
        "suggested_description": "This pre/post project evaluates whether a screening tool reduced falls.",
        "confirmed": False,
        "design": {"aim": "reduce falls", "primary_outcome": "fall rate"},
    }
    payload.update(overrides)
    return _mock_completion(json.dumps(payload))


def test_clarify_opening_turn_sends_dataset_schema_and_dictionary_not_raw_values(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")
    with SessionLocal() as db:
        db.add(
            Upload(
                project_id=project_id,
                filename="data.csv",
                original_filename="data.csv",
                status="active",
                col_types=json.dumps({"fall_date": "Date", "unit": "Category"}),
                dictionary_text="fall_date: date of the fall. unit: hospital unit.",
            )
        )
        db.commit()

    with patch("api.routers.ai.litellm.completion", return_value=_clarify_reply()) as mocked_completion:
        response = client.post(f"/ai/clarify/{project_id}", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmed"] is False
    assert body["suggested_title"] == "Fall-Risk Screening Impact on Falls Rate, Unit 3W"
    assert len(body["turns"]) == 1
    assert body["turns"][0]["role"] == "ai"

    system_content = mocked_completion.call_args.kwargs["messages"][0]["content"]
    assert "fall_date" in system_content
    assert "hospital unit" in system_content

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        design = json.loads(project.ai_project_design)
        outcome_val = design.get("primary_outcome")
        if isinstance(outcome_val, dict):
            assert outcome_val.get("label") == "fall rate"
        else:
            assert outcome_val == "fall rate"


def test_clarify_response_includes_design_for_live_understanding_card(client, monkeypatch):
    """ClarifyResponse must carry the merged design (including plain_restatement) back
    to the client on every turn, not just after a resume/reload -- ClarificationStage's
    Structured Understanding Card renders from this field directly."""
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_clarify_reply(
        design={"aim": "reduce falls", "primary_outcome": "fall rate", "plain_restatement": "Tracking monthly falls."},
    )):
        response = client.post(f"/ai/clarify/{project_id}", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["design"] is not None
    assert body["design"]["plain_restatement"] == "Tracking monthly falls."
    assert "status" in body["design"]

    with patch("api.routers.ai.litellm.completion") as mocked_completion:
        confirmed = client.post(f"/ai/clarify/{project_id}", json={"confirm": True})
    assert confirmed.status_code == 200, confirmed.text
    assert mocked_completion.call_count == 0
    confirmed_body = confirmed.json()
    assert confirmed_body["design"] is not None
    assert confirmed_body["design"]["plain_restatement"] == "Tracking monthly falls."

def test_clarify_scrubs_phi_from_resident_message_before_sending_to_llm(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_clarify_reply()) as mocked_completion:
        response = client.post(f"/ai/clarify/{project_id}", json={"message": "patient SSN 123-45-6789 was screened"})

    assert response.status_code == 200, response.text
    sent_messages = mocked_completion.call_args.kwargs["messages"]
    assert not any("123-45-6789" in m["content"] for m in sent_messages)


def test_clarify_accumulates_turns_and_confirms_on_agreement(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_clarify_reply(confirmed=False)):
        first = client.post(f"/ai/clarify/{project_id}", json={})
    assert first.status_code == 200, first.text
    assert first.json()["confirmed"] is False

    with patch("api.routers.ai.litellm.completion", return_value=_clarify_reply(confirmed=True, message="Sounds good, we agree.")):
        second = client.post(f"/ai/clarify/{project_id}", json={"message": "yes falls, but also length of stay"})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["confirmed"] is True
    assert len(body["turns"]) == 3  # ai opening, user reply, ai confirmation

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        state = json.loads(project.ai_clarification_state)
        assert state["confirmed"] is True


def test_clarify_rate_limited_like_chat(client, monkeypatch):
    _set_openrouter_provider()
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

    with patch("api.routers.ai.litellm.completion") as mocked_completion:
        response = client.post(f"/ai/clarify/{project_id}", json={})

    assert response.status_code == 429
    assert mocked_completion.call_count == 0


def _plan_reply(**overrides):
    payload = {
        "message": "Here's what I recommend...",
        "reasoning": "Matched the pre/post design to descriptive and run-chart methods.",
        "confirmed": False,
        "analyses": [
            {"template": "descriptive_summary", "rationale": "Baseline picture.", "parameters": {"value_cols": ["value"]}},
            {"template": "run_chart", "rationale": "Shows the trend over time.", "parameters": {"date_col": "fall_date", "value_col": "value"}},
        ],
    }
    payload.update(overrides)
    return _mock_completion(json.dumps(payload))


def test_recommend_plan_opening_turn_proposes_multiple_analyses_from_the_known_library(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")
    with SessionLocal() as db:
        db.add(
            Upload(
                project_id=project_id,
                filename="data.csv",
                original_filename="data.csv",
                status="active",
                col_types=json.dumps({"fall_date": "Date", "value": "Number"}),
                dictionary_text="fall_date: date of fall. value: falls per month.",
            )
        )
        project = db.query(Project).filter_by(id=project_id).first()
        project.ai_project_design = json.dumps({"primary_outcome": "fall rate", "time_structure": "monthly, pre/post"})
        db.commit()

    with patch("api.routers.ai.litellm.completion", return_value=_plan_reply()) as mocked_completion:
        response = client.post(f"/ai/recommend-plan/{project_id}", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmed"] is False
    assert [a["template"] for a in body["analyses"]] == ["descriptive_summary", "run_chart"]

    system_content = mocked_completion.call_args.kwargs["messages"][0]["content"]
    assert "descriptive_summary" in system_content
    assert "before_after_mean" in system_content  # full method library present, not just the picked ones
    assert "fall rate" in system_content  # confirmed project design included

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        plan = json.loads(project.ai_analysis_plan)
        assert plan["confirmed"] is False
        assert len(plan["analyses"]) == 2


def test_recommend_plan_drops_any_template_outside_the_known_library(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch(
        "api.routers.ai.litellm.completion",
        return_value=_plan_reply(analyses=[
            {"template": "descriptive_summary", "rationale": "ok", "parameters": {}},
            {"template": "custom_mixed_effects_model", "rationale": "not real", "parameters": {}},
        ]),
    ):
        response = client.post(f"/ai/recommend-plan/{project_id}", json={})

    assert response.status_code == 200, response.text
    assert [a["template"] for a in response.json()["analyses"]] == ["descriptive_summary"]


def test_recommend_plan_scrubs_phi_from_resident_message_before_sending_to_llm(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_plan_reply()) as mocked_completion:
        response = client.post(f"/ai/recommend-plan/{project_id}", json={"message": "patient SSN 123-45-6789 wants a t-test"})

    assert response.status_code == 200, response.text
    sent_messages = mocked_completion.call_args.kwargs["messages"]
    assert not any("123-45-6789" in m["content"] for m in sent_messages)


def test_recommend_plan_accumulates_turns_and_confirms_on_agreement(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_plan_reply(confirmed=False)):
        first = client.post(f"/ai/recommend-plan/{project_id}", json={})
    assert first.status_code == 200, first.text
    assert first.json()["confirmed"] is False

    with patch(
        "api.routers.ai.litellm.completion",
        return_value=_plan_reply(confirmed=True, message="Sounds good.", analyses=[
            {"template": "run_chart", "rationale": "Shows the trend.", "parameters": {"date_col": "fall_date", "value_col": "value"}},
        ]),
    ):
        second = client.post(f"/ai/recommend-plan/{project_id}", json={"message": "just the run chart is fine"})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["confirmed"] is True
    assert [a["template"] for a in body["analyses"]] == ["run_chart"]
    assert len(body["turns"]) == 3

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        plan = json.loads(project.ai_analysis_plan)
        assert plan["confirmed"] is True


def test_recommend_plan_rate_limited_like_chat(client, monkeypatch):
    _set_openrouter_provider()
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

    with patch("api.routers.ai.litellm.completion") as mocked_completion:
        response = client.post(f"/ai/recommend-plan/{project_id}", json={})

    assert response.status_code == 429
    assert mocked_completion.call_count == 0


def test_clarify_confirm_true_short_circuits_without_calling_the_llm(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_clarify_reply()) as mocked_completion:
        opening = client.post(f"/ai/clarify/{project_id}", json={})
    assert opening.status_code == 200, opening.text
    assert opening.json()["confirmed"] is False
    assert mocked_completion.call_count == 1

    with patch("api.routers.ai.litellm.completion") as mocked_completion_confirm:
        response = client.post(f"/ai/clarify/{project_id}", json={"confirm": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmed"] is True
    assert len(body["turns"]) == 1  # confirm doesn't add a new turn
    assert mocked_completion_confirm.call_count == 0  # no LLM round-trip needed

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        state = json.loads(project.ai_clarification_state)
        assert state["confirmed"] is True


def test_clarify_confirm_true_does_not_require_an_api_key(client):
    project_id = _project_id(client)

    response = client.post(f"/ai/clarify/{project_id}", json={"confirm": True})

    assert response.status_code == 200, response.text
    assert response.json()["confirmed"] is True


def test_clarify_retries_once_when_the_model_returns_empty_content_then_succeeds(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch(
        "api.routers.ai.litellm.completion",
        side_effect=[_mock_completion(""), _clarify_reply()],
    ) as mocked_completion:
        response = client.post(f"/ai/clarify/{project_id}", json={})

    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Here's what I understood about your project..."
    assert mocked_completion.call_count == 2
    second_call_kwargs = mocked_completion.call_args_list[1].kwargs
    assert second_call_kwargs["reasoning_effort"] == "minimal"


def test_clarify_fails_loud_instead_of_persisting_a_blank_turn_when_still_empty_after_retry(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion("")) as mocked_completion:
        response = client.post(f"/ai/clarify/{project_id}", json={})

    assert response.status_code == 502
    assert mocked_completion.call_count == 2

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project.ai_clarification_state is None  # no dead blank turn persisted


def test_recommend_plan_retries_once_when_the_model_returns_empty_content_then_succeeds(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch(
        "api.routers.ai.litellm.completion",
        side_effect=[_mock_completion(""), _plan_reply()],
    ) as mocked_completion:
        response = client.post(f"/ai/recommend-plan/{project_id}", json={})

    assert response.status_code == 200, response.text
    assert mocked_completion.call_count == 2


def test_recommend_plan_scrubs_dictionary_text_and_quality_findings_before_sending_to_llm(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")
    with SessionLocal() as db:
        db.add(
            Upload(
                project_id=project_id,
                filename="data.csv",
                original_filename="data.csv",
                status="active",
                col_types=json.dumps({"value": "Number"}),
                dictionary_text="value: falls per month. Contact SSN 123-45-6789 for questions.",
                quality_flags=json.dumps([
                    {"col": "clinician", "rule": "sparse_category", "msg": "level(s) with < 5 rows: {'SSN 123-45-6789': 2}"}
                ]),
            )
        )
        db.commit()

    with patch("api.routers.ai.litellm.completion", return_value=_plan_reply()) as mocked_completion:
        response = client.post(f"/ai/recommend-plan/{project_id}", json={})

    assert response.status_code == 200, response.text
    system_content = mocked_completion.call_args.kwargs["messages"][0]["content"]
    assert "123-45-6789" not in system_content


def test_recommend_plan_fails_loud_instead_of_persisting_a_blank_turn_when_still_empty_after_retry(client, monkeypatch):
    _set_openrouter_provider()
    project_id = _project_id(client)
    monkeypatch.setattr("api.routers.ai.settings.openrouter_api_key", "fake-key")

    with patch("api.routers.ai.litellm.completion", return_value=_mock_completion("")):
        response = client.post(f"/ai/recommend-plan/{project_id}", json={})

    assert response.status_code == 502

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project.ai_analysis_plan is None


