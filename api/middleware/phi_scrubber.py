import re
from typing import Tuple
import spacy

_nlp = spacy.load("en_core_web_sm")

_PATTERNS = [
    r'\bMRN[:\s#]*\d{5,10}\b',
    r'\b\d{3}-\d{2}-\d{4}\b',                    # SSN
    r'\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b',          # phone
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',  # email
    r'\bDOB[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b',
]


def scrub_text(text: str) -> Tuple[str, int]:
    count = 0
    for pattern in _PATTERNS:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        count += len(matches)
        text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
    doc = _nlp(text)
    spans = [ent for ent in doc.ents if ent.label_ in {"PERSON", "DATE", "ORG"}]
    for ent in reversed(spans):
        text = text[:ent.start_char] + "[REDACTED]" + text[ent.end_char:]
        count += 1
    return text, count
