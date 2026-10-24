import json

from api.ai_stub import canned_response


def _system_message(content: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": content}, {"role": "user", "content": "Please respond."}]


def test_canned_response_routes_by_system_prompt_phrase_only():
    messages = _system_message(
        "You are recommending a complete statistical analysis plan for a QI project. "
        "The user turn below mentions 'clarify' and 'interpret' but must not affect routing."
    )
    messages.append({"role": "user", "content": "Please clarify and interpret this as a recommendation."})

    content = json.loads(canned_response(messages).choices[0].message.content)

    assert "analyses" in content
    assert "message" in content


def test_canned_response_interpret_emits_one_interpretation_per_run_id_in_prompt():
    """The interpret system prompt embeds a results_payload JSON with one "run_id": <int>
    per analysis run. canned_response must derive interpretations from those exact ids
    (deduped, order preserved) rather than a hardcoded run_id, since real runs can have
    any ids and the caller's schema validation requires every referenced run_id to match."""
    system_prompt = (
        "You are writing a unified interpretation of statistical results for a medical "
        "resident's QI project abstract and report.\n"
        "Results: [{\"run_id\": 7, \"template\": \"descriptive_summary\"}, "
        "{\"run_id\": 9, \"template\": \"run_chart\"}]"
    )
    messages = _system_message(system_prompt)

    content = json.loads(canned_response(messages).choices[0].message.content)

    run_ids = [item["run_id"] for item in content["interpretations"]]
    assert run_ids == [7, 9]
    assert all(item["text"] for item in content["interpretations"])
    assert "limitations" in content
    assert "abstract_draft" in content


def test_canned_response_interpret_dedupes_repeated_run_ids():
    system_prompt = (
        "You are writing a unified interpretation of statistical results for a QI report.\n"
        "Results: [{\"run_id\": 3}, {\"run_id\": 3}, {\"run_id\": 5}]"
    )
    messages = _system_message(system_prompt)

    content = json.loads(canned_response(messages).choices[0].message.content)

    run_ids = [item["run_id"] for item in content["interpretations"]]
    assert run_ids == [3, 5]


def test_canned_response_interpret_falls_back_to_run_id_one_when_none_found():
    messages = _system_message("You are writing a unified interpretation of statistical results with no payload.")

    content = json.loads(canned_response(messages).choices[0].message.content)

    assert [item["run_id"] for item in content["interpretations"]] == [1]
