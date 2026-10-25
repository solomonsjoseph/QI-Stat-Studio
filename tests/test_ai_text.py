"""The QI Stat Advisor writes plain text in the house style: no Markdown, no dash punctuation, no stock phrases."""
import os

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

import json

from api import ai_prompts
from api.ai_text import clean_ai_data, clean_ai_text
from api.routers.ai import _extract_json_object


def test_markdown_markers_are_removed_and_the_words_stay():
    raw = "## Plan\n**Summary statistics** and *the* `p_chart` with ```r\nx\n```\n* first\n* second\n---\n| a | b |\n|---|---|"
    out = clean_ai_text(raw)
    assert "*" not in out.replace("- ", "") and "#" not in out and "`" not in out and "---" not in out
    assert "Summary statistics and the p_chart" in out
    assert "- first\n- second" in out


def test_dashes_become_ordinary_punctuation_and_ranges_read_as_words():
    out = clean_ai_text("It rose — slowly – to 17.4%–25.4%, over 5–30 days -- twice.")
    assert "—" not in out and "–" not in out and "--" not in out
    assert "17.4% to 25.4%" in out and "5 to 30 days" in out


def test_curly_quotes_arrows_and_emoji_are_plain():
    out = clean_ai_text("“good” it’s → fine \U0001F680")
    assert out == "\"good\" it's to fine"


def test_stock_phrases_are_replaced_in_the_same_case():
    out = clean_ai_text("It is worth noting that this is crucial. Crucial! The chart serves as a check and delves into trends.")
    assert "worth noting" not in out.lower() and "crucial" not in out.lower() and "serves as" not in out
    assert out.startswith("This is important.") and "Important!" in out


def test_identifiers_numbers_and_numbered_lists_are_left_alone():
    raw = "Use __init__ and pre_post_col.\n1. First step\n2. Second step\np = 0.03 (95% CI 1.1 to 14.7)"
    assert clean_ai_text(raw) == raw


def test_nested_model_output_is_cleaned_but_keys_are_not():
    data = {"message": "**Hi** — there", "items": [{"label": "*x*"}], "n": 3}
    assert clean_ai_data(data) == {"message": "Hi, there", "items": [{"label": "x"}], "n": 3}


def test_json_parsed_from_a_model_reply_comes_out_clean():
    reply = json.dumps({"message": "**Summary** — see below", "design": {"aim": "Reduce “falls”"}})
    parsed = _extract_json_object(reply)
    assert parsed["message"] == "Summary, see below" and parsed["design"]["aim"] == 'Reduce "falls"'


def test_every_system_prompt_carries_the_style_directive():
    templates = [v for k, v in vars(ai_prompts).items() if k.endswith(("_V1", "_V2")) and hasattr(v, "format")]
    assert templates
    for template in templates:
        assert "{IDENTITY_DIRECTIVE}" in str(template), template
    assert "Plain text only" in ai_prompts.IDENTITY_DIRECTIVE and "em dashes" in ai_prompts.IDENTITY_DIRECTIVE


def test_filler_and_lead_ins_are_plain():
    from api.ai_text import clean_ai_text
    assert clean_ai_text("Additionally, we did this in order to learn.") == "We did this to learn."
    assert clean_ai_text("Due to the fact that it is low, check it.") == "Because it is low, check it."


def test_empty_worth_noting_sentence_is_dropped():
    from api.ai_text import clean_ai_text
    assert clean_ai_text("The test is significant. That apparent tension is worth noting. A rise may be brief.") == "The test is significant. A rise may be brief."


def test_inline_numbered_list_goes_one_item_per_line():
    from api.ai_text import clean_ai_text
    out = clean_ai_text("There are three steps. 1. Load it. 2. Check it. 3. Run it.")
    assert out.splitlines() == ["There are three steps.", "1. Load it.", "2. Check it.", "3. Run it."]
    assert clean_ai_text("The rate was 0.05. 5. Not a list.") == "The rate was 0.05. 5. Not a list."
