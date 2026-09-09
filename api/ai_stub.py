from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

_CANNED_CLARIFY = json.dumps({
    "message": (
        "Based on your dataset with columns month, falls, and patient_days, here is my understanding:\n"
        "1. What specific patient safety intervention was introduced to reduce falls?\n"
        "2. When did this intervention begin (approximate start date)?"
    ),
    "reasoning": "Identified monthly fall counts and patient days on a clinical floor; clarifying intervention details.",
    "suggested_title": "Inpatient Falls Reduction Initiative",
    "suggested_description": "A quality improvement initiative to reduce inpatient falls per 1,000 patient-days over monthly observation periods.",
    "confirmed": False,
    "sufficient_to_continue": False,
    "design": {
        "aim": "Reduce monthly inpatient falls on the nursing floor",
        "population": "Hospitalized inpatients",
        "setting": "Inpatient medical unit",
        "intervention": {
            "present": True,
            "description": "Fall-risk assessment protocol and rounding",
            "start_date": None,
        },
        "primary_outcome": {
            "label": "Fall Rate (falls per 1,000 patient-days)",
            "column": "falls",
            "kind": "rate",
            "denominator_column": "patient_days",
        },
        "secondary_outcomes": [],
        "comparison": "time-series",
        "time_structure": {
            "has_dates": True,
            "date_column": "month",
            "granularity": "month",
        },
        "unit_of_analysis": "period",
        "group_column": None,
        "pre_label": None,
        "post_label": None,
        "paired": False,
        "pairing_id_column": None,
        "design_type": "Interrupted Time Series / Control Chart",
        "confidence": {
            "aim": "medium",
            "primary_outcome.column": "high",
            "time_structure.date_column": "high",
        },
        "plain_restatement": "Tracking monthly inpatient falls normalized by patient days over time.",
    },
})

_CANNED_RECOMMEND = json.dumps({
    "message": "I recommend a P/U chart for tracking monthly fall rates alongside a descriptive baseline summary.",
    "reasoning": "Monthly aggregate rates over time are suited for statistical process control.",
    "confirmed": False,
    "analyses": [
        {
            "id": "descriptive_summary-1",
            "template": "descriptive_summary",
            "display_name": "Summary of Monthly Counts and Patient Days",
            "question": "What were the average monthly falls and patient days?",
            "rationale": "Establishes basic distribution and missingness checks.",
            "parameters": {"value_cols": ["falls", "patient_days"]},
            "param_confidence": {"value_cols": "high"},
            "assumptions": ["Valid non-negative counts"],
            "limitations": ["Does not account for temporal ordering"],
        },
        {
            "id": "u_c_chart-2",
            "template": "u_c_chart",
            "display_name": "Monthly Fall Rate (U Chart)",
            "question": "Did the fall rate per patient day change or exhibit special cause variation?",
            "rationale": "Accounts for varying patient days as exposure denominator.",
            "parameters": {
                "date_col": "month",
                "count_col": "falls",
                "denominator_col": "patient_days",
            },
            "param_confidence": {
                "date_col": "high",
                "count_col": "high",
                "denominator_col": "high",
            },
            "assumptions": ["Poisson distribution for count rates"],
            "limitations": ["Requires regular monthly intervals"],
        },
    ],
})

_CANNED_COLLECTION = json.dumps({
    "recommendations": [
        {
            "id": "record-fall-severity",
            "title": "Track fall severity or injury level",
            "why": "Distinguishing falls with injury from unassisted minor slips provides a vital balancing measure.",
            "severity": "important",
            "necessity": "recommended",
            "source": "ai",
        },
        {
            "id": "track-staffing-ratio",
            "title": "Consider nurse-to-patient staffing ratio",
            "why": "Staffing changes can confound fall rate trends across observation periods.",
            "severity": "info",
            "necessity": "optional",
            "source": "ai",
        },
    ]
})

_CANNED_OVERRIDE = json.dumps({
    "message": "Adjusted the analysis plan per your request.",
    "changes": ["Added run chart for simplified timeline plotting."],
    "confirmed": False,
    "analyses": [
        {
            "id": "run_chart-1",
            "template": "run_chart",
            "display_name": "Monthly Fall Count (Run Chart)",
            "question": "Is there a non-random trend in monthly falls?",
            "rationale": "Run chart evaluation using median rules.",
            "parameters": {"date_col": "month", "value_col": "falls"},
            "param_confidence": {"date_col": "high", "value_col": "high"},
            "assumptions": ["Continuous or discrete ordered counts"],
            "limitations": ["Does not normalize by patient days"],
        }
    ],
})

_INTERPRET_TEXTS = [
    "Monthly falls averaged 2.5 across the evaluated baseline periods.",
    "The observed rate remained within expected control limits across the evaluated periods, with no sustained special-cause signal.",
    "The comparison showed a consistent shift between the pre- and post-intervention periods, aligned with the stated aim.",
]

_CANNED_INTERPRET_LIMITATIONS = [
    "Single-site clinical floor implementation without randomized controls.",
    "Unmeasured clinical acuity may have varied across months.",
]

_CANNED_INTERPRET_ABSTRACT = (
    "Background: Inpatient falls are a leading cause of hospital-acquired complications. "
    "Methods: We evaluated monthly fall counts and rates per patient day. "
    "Results: Average fall count was 2.5 per month with stable baseline variation. "
    "Conclusions: Targeted fall-risk assessments are recommended for ongoing clinical review."
)


def _canned_interpret(system_text: str) -> str:
    """Build one interpretation per run_id embedded in the interpret-results prompt's
    <untrusted_data> results payload, rather than hardcoding run_id 1 -- a real prompt
    can reference any number of runs with any ids, and every referenced run must get a
    response or the caller's schema validation (run_id must match a real run) fails.
    """
    run_ids = list(dict.fromkeys(int(m) for m in re.findall(r'"run_id"\s*:\s*(\d+)', system_text)))
    if not run_ids:
        run_ids = [1]
    interpretations = [
        {"run_id": run_id, "text": _INTERPRET_TEXTS[idx % len(_INTERPRET_TEXTS)]}
        for idx, run_id in enumerate(run_ids)
    ]
    return json.dumps({
        "interpretations": interpretations,
        "limitations": _CANNED_INTERPRET_LIMITATIONS,
        "abstract_draft": _CANNED_INTERPRET_ABSTRACT,
    })

def canned_response(messages: list[dict[str, str]]) -> SimpleNamespace:
    """Return a canned SimpleNamespace mock response matching the prompt context.

    Matches ONLY the system prompt (messages[0]) against phrases that are unique to
    each prompt template in api/ai_prompts.py -- never the full conversation, since
    user turns and untrusted dictionary/description text can legitimately contain
    words like "clarify" or "recommend" and would otherwise route to the wrong
    canned schema, failing response validation.
    """
    system_text = (messages[0].get("content", "") if messages else "").lower()

    if "clarify a quality-improvement" in system_text or "what are you measuring" in system_text:
        content = _CANNED_CLARIFY
    elif "adjusting an existing statistical analysis plan" in system_text:
        content = _CANNED_OVERRIDE
    elif "methodology advisor reviewing" in system_text:
        content = _CANNED_COLLECTION
    elif "recommending a complete statistical analysis plan" in system_text:
        content = _CANNED_RECOMMEND
    elif "unified interpretation of statistical results" in system_text:
        content = _canned_interpret(system_text)
    else:
        content = _CANNED_CLARIFY

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
