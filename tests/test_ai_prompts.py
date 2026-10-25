

def test_every_system_prompt_names_the_advisor_and_has_no_unfilled_identity_placeholder():
    from api import ai_prompts

    names = [n for n in dir(ai_prompts) if n.endswith(tuple(f"_V{i}" for i in range(1, 6))) and n.endswith(tuple(f"_V{i}" for i in range(1, 6))) and "SYSTEM" in n]
    assert len(names) >= 8
    for name in names:
        text = getattr(ai_prompts, name).format()
        assert "You are the QI Stat Advisor" in text, name
        assert "{IDENTITY_DIRECTIVE}" not in text, name
