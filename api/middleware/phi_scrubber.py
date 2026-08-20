from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Tuple

import pandas as pd
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
    r"\(\d{3}\)\s*\d{3}[-.\s]?\d{4}\b",  # phone, parenthesized area code
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # email
    r"\b\d{1,6}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,4}\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Place|Pl)\b",
]

# Date-shaped patterns are split out from _PATTERNS: most callers want them redacted
# (a date in free-text chat could easily be a patient's DOB), but a caller that is
# specifically asking the resident for a project-level date (an intervention date,
# an abstract deadline) needs that exact date to survive scrubbing -- redacting it
# defeats the purpose of asking. See scrub_text(redact_dates=...).
_DATE_PATTERNS = [
    r"\bDOB[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",  # standalone MM/DD/YYYY date
    r"\b\d{1,2}/\d{1,2}/\d{2}\b",  # standalone MM/DD/YY date
    r"\b\d{4}-\d{2}-\d{2}\b",  # standalone YYYY-MM-DD date
]


def scrub_text(text: str, redact_dates: bool = True) -> Tuple[str, int]:
    """Redact obvious PHI with regexes and, when available, spaCy NER.

    This scrubber is defense-in-depth for accidental disclosure, not a guarantee
    that arbitrary clinical text is PHI-free. Callers must never log original
    content or treat redaction as a substitute for minimum-necessary prompting.

    redact_dates=False skips date-shaped regexes and the NER DATE label -- use
    this only when the caller is specifically asking for a project-level date
    (an intervention date, an abstract deadline), where the date itself is the
    answer being extracted, not incidental text that might be a patient's DOB.
    Names, MRNs, SSNs, phone numbers, emails, and addresses are still redacted
    either way.
    """
    count = 0
    patterns = _PATTERNS + _DATE_PATTERNS if redact_dates else _PATTERNS
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        count += len(matches)
        text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
    if _nlp is None:
        return text, count
    doc = _nlp(text)
    ner_labels = {"PERSON", "DATE", "ORG"} if redact_dates else {"PERSON", "ORG"}
    spans = [ent for ent in doc.ents if ent.label_ in ner_labels]
    for ent in reversed(spans):
        text = text[:ent.start_char] + "[REDACTED]" + text[ent.end_char:]
        count += 1
    return text, count


# --- Deterministic, non-AI dataset PHI gate -------------------------------
# No LLM ever sees dataset contents here: this is pure column-name/value
# pattern matching, run before an uploaded file is stored.

_NAME_COL_RE = re.compile(r"(patient.*name|pt.*name|full.?name|last.?name|first.?name|^name$)", re.I)
_MRN_COL_RE = re.compile(r"(mrn|medical.?record)", re.I)
_SSN_COL_RE = re.compile(r"(ssn|social.?security)", re.I)
_DOB_COL_RE = re.compile(r"(dob|date.?of.?birth|birth.?date)", re.I)
_ADDRESS_COL_RE = re.compile(r"(address|street)", re.I)
_PHONE_COL_RE = re.compile(r"phone", re.I)
_EMAIL_COL_RE = re.compile(r"email", re.I)
_AGE_COL_RE = re.compile(r"^age([_ ]?(years|yrs))?$", re.I)

_VALUE_CATEGORY_PATTERNS = [
    ("Medical Record Number", re.compile(r"\bMRN[:\s#]*\d{5,10}\b", re.I)),
    ("Social Security Number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("Phone Number", re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b|\(\d{3}\)\s*\d{3}[-.\s]?\d{4}\b")),
    ("Email Address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]

# Real identifier categories can never be talked out of by a data dictionary --
# there is no legitimate non-identifying reading of an actual name/MRN/SSN/DOB.
_NON_CLEARABLE_CATEGORIES = {"Patient Name", "Medical Record Number", "Social Security Number", "Date of Birth"}
_CLEARING_PHRASES = ("de-identified", "non-identifying", "not phi", "sequential id", "study id", "randomly assigned")


@dataclass
class PhiViolation:
    column: str
    category: str
    message: str


@dataclass
class PhiScanResult:
    violations: list = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.violations)


def _dictionary_clears_column(column: str, dictionary_text: str) -> bool:
    text = dictionary_text.lower()
    idx = text.find(column.lower())
    if idx == -1:
        return False
    window = text[idx: idx + 300]
    return any(phrase in window for phrase in _CLEARING_PHRASES)


def scan_dataframe_for_phi(df: pd.DataFrame, dictionary_text: str | None = None) -> PhiScanResult:
    """Deterministic, zero-tolerance PHI scan of an uploaded dataset.

    Checks column names against identifier heuristics and cell values against
    the same regex patterns used by scrub_text. A single matching cell or
    column name is a violation. Never reads/logs raw PHI values -- only the
    column name and violation category are returned.
    """
    has_age_column = any(_AGE_COL_RE.search(str(col)) for col in df.columns)
    violations: list[PhiViolation] = []

    for col in df.columns:
        col_str = str(col)
        category: str | None = None
        message: str | None = None

        if _NAME_COL_RE.search(col_str):
            category = "Patient Name"
            message = f'"{col_str}" looks like a patient name column. Remove it.'
        elif _MRN_COL_RE.search(col_str):
            category = "Medical Record Number"
            message = f'"{col_str}" looks like a medical record number column. Remove it.'
        elif _SSN_COL_RE.search(col_str):
            category = "Social Security Number"
            message = f'"{col_str}" looks like a Social Security Number column. Remove it.'
        elif _DOB_COL_RE.search(col_str):
            category = "Date of Birth"
            if has_age_column:
                message = f'"{col_str}" — remove this column, age is already available and date of birth is not needed.'
            else:
                message = f'"{col_str}" — this is a HIPAA violation. Convert this to age (or an age range) instead of date of birth, then re-upload.'
        elif _ADDRESS_COL_RE.search(col_str):
            category = "Address"
            message = f'"{col_str}" looks like a street address column. Remove it.'
        elif _PHONE_COL_RE.search(col_str):
            category = "Phone Number"
            message = f'"{col_str}" looks like a phone number column. Remove it.'
        elif _EMAIL_COL_RE.search(col_str):
            category = "Email Address"
            message = f'"{col_str}" looks like an email address column. Remove it.'
        else:
            values = df[col].dropna().astype(str)
            for value_category, pattern in _VALUE_CATEGORY_PATTERNS:
                if values.apply(lambda v: bool(pattern.search(v))).any():
                    category = value_category
                    message = f'"{col_str}" contains values that look like a {value_category.lower()}. Remove it.'
                    break

        if category is None:
            continue

        clearable = category not in _NON_CLEARABLE_CATEGORIES
        if clearable and dictionary_text and _dictionary_clears_column(col_str, dictionary_text):
            continue

        violations.append(PhiViolation(column=col_str, category=category, message=message))

    return PhiScanResult(violations=violations)
