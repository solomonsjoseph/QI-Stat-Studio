from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd
import spacy

from api.middleware.phi_scrubber import (
    _VALUE_CATEGORY_PATTERNS,
    scan_dataframe_for_phi,
)

logger = logging.getLogger(__name__)

try:
    _nlp = spacy.load("en_core_web_sm")
except Exception as exc:
    _nlp = None
    logger.warning("spaCy PHI NER model unavailable in phi_gate: %s", exc)

PhiStatus = Literal["pending", "passed", "blocked", "error"]


@dataclass
class PhiFinding:
    source: str        # "dataset" | "dictionary"
    column: str | None # None for document findings
    category: str
    message: str


@dataclass
class PhiGateResult:
    status: PhiStatus
    findings: list[PhiFinding]


_EXCLUDED_PERSON_WORDS = {
    "mrn", "ssn", "dob", "id", "pt", "dx", "rx", "ref", "date", "age",
    "num", "code", "batch", "status", "period", "value", "table",
    "dataset", "column", "patient", "encounter", "doctor", "nurse",
    "hospital", "clinic", "study", "trial", "site", "subject", "file",
}


def _is_valid_person_entity(ent) -> bool:
    cleaned = ent.text.strip().lower()
    if cleaned in _EXCLUDED_PERSON_WORDS:
        return False
    if len(ent.text.split()) == 1 and ent.text.islower():
        return False
    return True


def scan_document_text(text: str) -> list[PhiFinding]:
    """Scan document prose for value-level PHI patterns and person names.

    Does not apply column-name heuristics so documenting a column like 'patient_name'
    does not flag itself.
    """
    if not text or not text.strip():
        return []

    findings: list[PhiFinding] = []

    # Value-level regex patterns (MRN, SSN, Phone, Email)
    for category, pattern in _VALUE_CATEGORY_PATTERNS:
        if pattern.search(text):
            findings.append(
                PhiFinding(
                    source="dictionary",
                    column=None,
                    category=category,
                    message=f"Document contains a {category.lower()}. Remove it.",
                )
            )

    # Person-name check via spaCy NER
    if _nlp is not None:
        doc = _nlp(text)
        has_person = any(ent.label_ == "PERSON" and _is_valid_person_entity(ent) for ent in doc.ents)
        if has_person:
            findings.append(
                PhiFinding(
                    source="dictionary",
                    column=None,
                    category="Patient Name",
                    message="Document contains a person name. Remove it.",
                )
            )

    return findings


def scan_upload(df: pd.DataFrame, dictionary_text: str | None) -> PhiGateResult:
    """Zero-tolerance PHI scan of both dataset and supporting document.

    Fails closed on any scanner exception with status='error'.
    """
    try:
        # Scan dictionary first to determine if it has PHI
        dict_findings: list[PhiFinding] = []
        if dictionary_text:
            dict_findings = scan_document_text(dictionary_text)

        # If dictionary produced a finding, it cannot clear any dataset column
        effective_dict_text = None if dict_findings else dictionary_text

        df_result = scan_dataframe_for_phi(df, dictionary_text=effective_dict_text)

        df_findings = [
            PhiFinding(
                source="dataset",
                column=v.column,
                category=v.category,
                message=v.message,
            )
            for v in df_result.violations
        ]

        all_findings = df_findings + dict_findings
        if all_findings:
            return PhiGateResult(status="blocked", findings=all_findings)
        return PhiGateResult(status="passed", findings=[])
    except Exception:
        logger.exception("phi_scan_failed")
        return PhiGateResult(status="error", findings=[])
