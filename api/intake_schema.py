from __future__ import annotations

import re
from typing import Any

from fastapi.exceptions import RequestValidationError

NO_COMPARISON = "No — I'm just describing one time period"

QUESTIONS: dict[str, dict[str, Any]] = {
    "q1": {"type": "text"},
    "q2": {
        "type": "radio",
        "options": [
            "A rate of events over time (infections per 1,000 catheter-days)",
            "A percentage or proportion (percent of patients screened)",
            "A count (number of falls per month)",
            "An average or median value (average LDL)",
            "A yes/no outcome (did the patient get a flu shot)",
            "Something else / not sure",
        ],
    },
    "q3": {
        "type": "radio",
        "options": [
            "Yes — before and after an intervention",
            NO_COMPARISON,
            "More than two periods (phases)",
            "I'm not sure",
        ],
    },
    "q4": {
        "type": "radio",
        "options": [
            "Tracking over time (months, weeks, days)",
            "Comparing groups at one point in time",
            "Both",
            "I'm not sure",
        ],
    },
    "q5": {
        "type": "radio",
        "options": ["Daily", "Weekly", "Monthly", "One row per patient", "Other", "I'm not sure"],
    },
    "q6": {"type": "number"},
    "q7": {"type": "composite", "fields": {"description", "date"}},
    "q8": {
        "type": "radio",
        "options": ["Same unit pre vs. post", "Intervention vs. control", "Subgroups", "I'm not sure"],
    },
    "q9": {"type": "radio", "options": ["R", "SPSS", "SAS", "All three"]},
    "q10": {"type": "composite", "fields": {"email", "deadline"}},
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

_SHORT_LABELS: dict[str, dict[str, str]] = {
    "q2": {
        "percent": "A percentage or proportion (percent of patients screened)",
        "percentage": "A percentage or proportion (percent of patients screened)",
        "proportion": "A percentage or proportion (percent of patients screened)",
        "yes/no": "A yes/no outcome (did the patient get a flu shot)",
        "yes-no": "A yes/no outcome (did the patient get a flu shot)",
        "yes no": "A yes/no outcome (did the patient get a flu shot)",
        "average": "An average or median value (average LDL)",
        "mean": "An average or median value (average LDL)",
        "median": "An average or median value (average LDL)",
        "rate": "A rate of events over time (infections per 1,000 catheter-days)",
        "count": "A count (number of falls per month)",
    },
    "q3": {
        "yes": "Yes — before and after an intervention",
        "before-after": "Yes — before and after an intervention",
        "before after": "Yes — before and after an intervention",
        "no": NO_COMPARISON,
        "one-period": NO_COMPARISON,
        "one period": NO_COMPARISON,
    },
}


def _validation_error(field_errors: dict[str, list[str]]) -> RequestValidationError:
    errors = []
    for field, messages in field_errors.items():
        for message in messages:
            errors.append({"loc": ("body", "answers", field), "msg": message, "type": "value_error"})
    return RequestValidationError(errors)


def _canonical_radio(key: str, value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return ""

    lowered = text.lower()
    if lowered in _SHORT_LABELS.get(key, {}):
        return _SHORT_LABELS[key][lowered]

    for option in QUESTIONS[key]["options"]:
        if text == option or lowered == option.lower():
            return option
    return None


def _validate_q6(value: Any) -> int | str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().lower() == "i'm not sure":
        return "I'm not sure"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def _validate_q7(value: Any) -> dict[str, str] | None:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        return None
    allowed = {"description", "date"}
    if set(value) - allowed:
        return None
    result: dict[str, str] = {}
    description = value.get("description")
    date = value.get("date")
    if description not in (None, ""):
        result["description"] = str(description)
    if date not in (None, ""):
        date_text = str(date)
        if not _DATE_RE.fullmatch(date_text):
            return None
        result["date"] = date_text
    return result


def _validate_q10(value: Any) -> dict[str, str] | None:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        return None
    allowed = {"email", "deadline"}
    if set(value) - allowed:
        return None
    result: dict[str, str] = {}
    email = value.get("email")
    deadline = value.get("deadline")
    if email not in (None, ""):
        email_text = str(email)
        if not _EMAIL_RE.fullmatch(email_text):
            return None
        result["email"] = email_text
    if deadline not in (None, ""):
        deadline_text = str(deadline)
        if not _DATE_RE.fullmatch(deadline_text):
            return None
        result["deadline"] = deadline_text
    return result


def is_unsure_answer(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(sub_value).strip() == "I'm not sure" for sub_value in value.values())
    return "I'm not sure" in str(value)


def validate_answers(
    raw_answers: dict[str, Any],
    existing_answers: dict[str, Any] | None = None,
    *,
    drop_unmatched: bool = False,
) -> tuple[dict[str, Any], set[str]]:
    field_errors: dict[str, list[str]] = {}
    normalized: dict[str, Any] = {}

    for key, value in raw_answers.items():
        if key not in QUESTIONS:
            if drop_unmatched:
                continue
            field_errors.setdefault(key, []).append("Unknown intake question")
            continue

        q_type = QUESTIONS[key]["type"]
        if q_type == "text":
            normalized[key] = "" if value is None else str(value)
        elif q_type == "radio":
            canonical = _canonical_radio(key, value)
            if canonical is None:
                if drop_unmatched:
                    continue
                field_errors.setdefault(key, []).append("Invalid option")
            else:
                normalized[key] = canonical
        elif key == "q6":
            number = _validate_q6(value)
            if number is None:
                if drop_unmatched:
                    continue
                field_errors.setdefault(key, []).append("Must be an integer greater than or equal to 0")
            else:
                normalized[key] = number
        elif key == "q7":
            q7 = _validate_q7(value)
            if q7 is None:
                if drop_unmatched:
                    continue
                field_errors.setdefault(key, []).append("Must include optional description and YYYY-MM-DD date")
            else:
                normalized[key] = q7
        elif key == "q10":
            q10 = _validate_q10(value)
            if q10 is None:
                if drop_unmatched:
                    continue
                field_errors.setdefault(key, []).append("Must include optional email and YYYY-MM-DD deadline")
            else:
                normalized[key] = q10

    if field_errors:
        raise _validation_error(field_errors)

    merged = {**(existing_answers or {}), **normalized}
    keys_to_delete: set[str] = set()
    if merged.get("q3") == NO_COMPARISON:
        normalized.pop("q7", None)
        normalized.pop("q8", None)
        keys_to_delete.update({"q7", "q8"})

    return normalized, keys_to_delete
