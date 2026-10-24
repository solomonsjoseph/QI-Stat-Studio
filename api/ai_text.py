"""House style for text the QI Stat Advisor writes: plain text, no Markdown, none of the usual signs of AI writing.

The prompts ask for this (api/ai_prompts.py). This module enforces it on what comes back, because a model
follows an instruction most of the time and not every time. It changes form only (markers, punctuation,
a short list of stock phrases), never the content of a finding.
"""

from __future__ import annotations

import re
from typing import Any

_FENCE = re.compile(r"```[A-Za-z0-9_-]*\n?")
_CODE = re.compile(r"`([^`\n]*)`")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)  # double underscores are left alone: they can be identifiers
_ITALIC = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_STAR_BULLET = re.compile(r"^([ \t]*)[*•][ \t]+", re.M)
_RULE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$\n?", re.M)
_TABLE_BAR = re.compile(r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$\n?", re.M)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆✅❌]")

_RANGE_DASH = re.compile(r"(?<=[\d%)])\s*[\u2013\u2014]\s*(?=\d)")
_SPACED_DASH = re.compile(r"\s+(?:[\u2014\u2013]|--)\s+")
_TIGHT_DASH = re.compile(r"\s*\u2014\s*")
_LONE_EN_DASH = re.compile(r"\u2013")

# Stock phrases and words that mark machine-written text, with a plain replacement. Form of the word only.
_PHRASES = [
    (re.compile(r"\bdelves into\b", re.I), "looks at"),
    (re.compile(r"\bdelved into\b", re.I), "looked at"),
    (re.compile(r"\bdelving into\b", re.I), "looking at"),
    (re.compile(r"\bdelve into\b", re.I), "look at"),
    (re.compile(r"\bplays? a (?:vital|crucial|pivotal|key) role in\b", re.I), "matters for"),
    (re.compile(r"\bserves as\b", re.I), "is"),
    (re.compile(r"\bstands as\b", re.I), "is"),
    (re.compile(r"\bboasts\b", re.I), "has"),
    (re.compile(r"\b(?:crucial|pivotal|vital)\b", re.I), "important"),
    (re.compile(r"\bleverag(?:e|es|ed|ing)\b", re.I), "use"),
    (re.compile(r"\bshowcas(?:e|es|ed|ing)\b", re.I), "show"),
    (re.compile(r"\bunderscor(?:e|es|ed|ing)\b", re.I), "show"),
]
# A lead-in with no content. The next word takes over its capital letter.
_LEAD_INS = re.compile(r"\b(it(?:'s| is) (?:worth noting|important to note) that)\s+(\w)", re.I)


def _match_case(original: str, replacement: str) -> str:
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def clean_ai_text(text: str) -> str:
    """Return the text as plain prose: no Markdown, straight quotes, no dash used as punctuation."""
    if not text:
        return text
    out = _FENCE.sub("", text)
    out = _CODE.sub(r"\1", out)
    out = _BOLD.sub(r"\1", out)
    out = _ITALIC.sub(r"\1", out)
    out = _HEADING.sub("", out)
    out = _RULE.sub("", out)
    out = _TABLE_BAR.sub("", out)
    out = _STAR_BULLET.sub(r"\1- ", out)
    out = _EMOJI.sub("", out)
    out = out.replace("→", " to ").replace("←", " from ")
    out = out.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    out = out.replace("…", "...")
    out = _RANGE_DASH.sub(" to ", out)
    out = _SPACED_DASH.sub(", ", out)
    out = _TIGHT_DASH.sub(", ", out)
    out = _LONE_EN_DASH.sub("-", out)
    out = _LEAD_INS.sub(lambda m: m.group(2).upper() if m.group(1)[0].isupper() else m.group(2), out)
    for pattern, replacement in _PHRASES:
        out = pattern.sub(lambda m, r=replacement: _match_case(m.group(0), r), out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def clean_ai_data(value: Any) -> Any:
    """clean_ai_text on every string inside parsed model output (keys are left alone)."""
    if isinstance(value, str):
        return clean_ai_text(value)
    if isinstance(value, list):
        return [clean_ai_data(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_ai_data(item) for key, item in value.items()}
    return value
