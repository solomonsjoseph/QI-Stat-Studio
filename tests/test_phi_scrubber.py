import pandas as pd

from api.middleware import phi_scrubber
from api.middleware.phi_scrubber import scan_dataframe_for_phi, scrub_text


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


def test_redacts_two_digit_year_date():
    result, count = scrub_text("Seen on 3/4/24 at the clinic")
    assert "3/4/24" not in result
    assert count >= 1


def test_redacts_parenthesized_phone():
    result, count = scrub_text("Reached patient at (908) 555-0199 to schedule")
    assert "(908) 555-0199" not in result
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


def test_scan_flags_patient_name_and_mrn_columns():
    df = pd.DataFrame({
        "patient_name": ["Jane Doe", "John Smith"],
        "mrn": [100234, 100567],
        "age": [72, 65],
    })
    result = scan_dataframe_for_phi(df)
    categories = {v.column: v.category for v in result.violations}
    assert categories == {"patient_name": "Patient Name", "mrn": "Medical Record Number"}
    assert result.blocked is True


def test_scan_permits_sequential_and_synthetic_id_columns():
    # Sequential small ints (pt_id) and non-identifying synthetic codes
    # (patient_id like "P10270") are internal IDs, not PHI -- never flagged
    # purely for being named "id"-like.
    df = pd.DataFrame({
        "pt_id": [1, 2, 3, 4],
        "patient_id": ["P10270", "P10271", "P10272", "P10273"],
        "age": [72, 65, 50, 44],
    })
    result = scan_dataframe_for_phi(df)
    assert result.blocked is False


def test_scan_dob_message_varies_with_age_presence():
    with_age = scan_dataframe_for_phi(pd.DataFrame({"dob": ["1/2/1980"], "age": [45]}))
    assert "already available" in with_age.violations[0].message

    without_age = scan_dataframe_for_phi(pd.DataFrame({"dob": ["1/2/1980"]}))
    assert "Convert this to age" in without_age.violations[0].message


def test_scan_dictionary_cannot_clear_real_identifier_categories():
    df = pd.DataFrame({
        "patient_name": ["Jane Doe"],
        "mrn": [100234],
        "dob": ["1/2/1980"],
    })
    dictionary_text = (
        "patient_name: non-identifying. mrn: de-identified study id. "
        "dob: not phi, sequential id."
    )
    result = scan_dataframe_for_phi(df, dictionary_text=dictionary_text)
    assert {v.column for v in result.violations} == {"patient_name", "mrn", "dob"}


def test_scan_flags_value_level_ssn_in_generically_named_column():
    df = pd.DataFrame({"notes": ["SSN 123-45-6789", "nothing here"]})
    result = scan_dataframe_for_phi(df)
    assert result.violations[0].category == "Social Security Number"


def test_scan_dictionary_clears_an_incidental_value_scan_match():
    # A phone-shaped reference code in a generic column is a clearable category
    # (Phone Number, found via value-scan, not a real-identifier column-name
    # match) -- the dictionary can clear this one, unlike name/mrn/ssn/dob.
    df = pd.DataFrame({"batch_ref": ["555-123-4567", "555-987-6543"]})
    result = scan_dataframe_for_phi(df)
    assert result.violations[0].category == "Phone Number"

    cleared = scan_dataframe_for_phi(
        df, dictionary_text="batch_ref: an internal batch code formatted like a phone number, non-identifying, not phi."
    )
    assert cleared.blocked is False


def test_scan_clean_dataset_passes():
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "fall_date": ["2026-01-04", "2026-01-09", "2026-01-15"],
        "unit": ["3W", "3W", "3W"],
        "age": [72, 65, 80],
    })
    result = scan_dataframe_for_phi(df)
    assert result.blocked is False
