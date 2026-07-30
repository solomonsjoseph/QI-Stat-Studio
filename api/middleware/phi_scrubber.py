import logging
import re
from typing import Tuple

import spacy

logger = logging.getLogger(__name__)

try:
    _nlp = spacy.load("en_core_web_sm")
except Exception as exc:  # pragma: no cover - environment-dependent startup branch
    _nlp = None
    logger.warning("spaCy PHI NER model unavailable; regex PHI scrubber remains active: %s", exc)

_PATTERNS = [
    r"\bMRN[:\s#]*\d{5,10}\b",
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
    r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",  # phone
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # email
    r"\bDOB[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",  # standalone MM/DD/YYYY date
    r"\b\d{4}-\d{2}-\d{2}\b",  # standalone YYYY-MM-DD date
    r"\b\d{1,6}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,4}\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Place|Pl)\b",
]


def scrub_text(text: str) -> Tuple[str, int]:
    """Redact obvious PHI with regexes and, when available, spaCy NER.

    This scrubber is defense-in-depth for accidental disclosure, not a guarantee
    that arbitrary clinical text is PHI-free. Callers must never log original
    content or treat redaction as a substitute for minimum-necessary prompting.
    """
    count = 0
    for pattern in _PATTERNS:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        count += len(matches)
        text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
    if _nlp is None:
        return text, count
    doc = _nlp(text)
    spans = [ent for ent in doc.ents if ent.label_ in {"PERSON", "DATE", "ORG"}]
    for ent in reversed(spans):
        text = text[:ent.start_char] + "[REDACTED]" + text[ent.end_char:]
        count += 1
    return text, count
