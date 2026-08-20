from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import litellm
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.config import settings
from api.database import get_db
from api.intake_schema import validate_answers
from api.middleware.phi_scrubber import scrub_text
from api.analysis_schemas import TEMPLATE_PARAM_MODELS
from api.routers.analyze import _ALL as ANALYSIS_TEMPLATES
from api.routers.analyze import _DESCRIPTIONS as ANALYSIS_DESCRIPTIONS
from api.models_api import (
    AnalysisPlanRequest,
    AnalysisPlanResponse,
    ChatRequest,
    ChatResponse,
    ClarifyRequest,
    ClarifyResponse,
    IntakePrefillRequest,
    IntakePrefillResponse,
    ScrubPreviewRequest,
    ScrubPreviewResponse,
)
from api.audit import log_action, safe_diagnostic_message
from api.models_db import AIUsageEvent, Project, Upload, User
from api.settings_registry import get_runtime_setting

router = APIRouter(prefix="/ai", tags=["ai"])


class _IntakePrefillDraft(BaseModel):
    q2: Any = None
    q3: Any = None
    q4: Any = None
    q5: Any = None
    q6: Any = None
    q7: Any = None

    model_config = ConfigDict(extra="ignore")


def _require_project_access(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if user.role != "admin" and project.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Project access denied")
    return project


def _extract_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end < start:
            return {}
        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}



_MODEL_PREFIXES = {
    "openrouter": "openrouter/",
    "openai": "openai/",
    "local": "ollama_chat/",
}


def _provider_settings(db: Session) -> tuple[str, str | None, str | None, str]:
    """Resolve (provider, api_key, api_base, default_model) for the configured AI provider."""
    provider = (get_runtime_setting(db, "ai_provider") or settings.ai_provider or "openrouter").strip().lower()
    if provider == "openai":
        model = get_runtime_setting(db, "openai_model") or settings.openai_model
        return provider, settings.openai_api_key or None, None, model
    if provider == "local":
        model = get_runtime_setting(db, "local_model") or settings.local_model
        base = get_runtime_setting(db, "local_api_base") or settings.local_api_base or "http://localhost:11434"
        return provider, settings.local_api_key or None, base, model
    model = get_runtime_setting(db, "openrouter_model") or settings.openrouter_model
    return "openrouter", settings.openrouter_api_key or None, None, model


def _llm_completion(
    provider: str,
    api_key: str | None,
    api_base: str | None,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 800,
    reasoning_effort: str | None = None,
):
    """Route a chat completion through litellm's unified, OpenAI-compatible interface."""
    kwargs: dict[str, Any] = {
        "model": f"{_MODEL_PREFIXES[provider]}{model}",
        "messages": messages,
        "max_tokens": max_tokens,
        "timeout": 30,
        "num_retries": 2,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    # Reasoning models (e.g. gpt-5-nano) can spend the entire max_tokens budget on
    # hidden reasoning and return empty content for anything beyond a trivial prompt;
    # capping reasoning effort keeps a real answer inside the token budget. Not every
    # configured provider/model supports this param, so let litellm drop it silently
    # rather than erroring out non-reasoning models.
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
        kwargs["drop_params"] = True
    return litellm.completion(**kwargs)


def _record_ai_usage(
    db: Session,
    *,
    user_id: int | None,
    project_id: int | None,
    model: str,
    prompt_chars: int,
    completion_chars: int = 0,
    status: str,
) -> None:
    db.add(
        AIUsageEvent(
            user_id=user_id,
            project_id=project_id,
            model=model,
            prompt_chars=prompt_chars,
            completion_chars=completion_chars,
            status=status,
        )
    )
    db.commit()

def _enforce_ai_rate_limit(db: Session, user: User) -> None:
    limit = get_runtime_setting(db, "ai_rate_limit_per_hour") or 20
    since = datetime.utcnow() - timedelta(hours=1)
    used = db.query(AIUsageEvent).filter(AIUsageEvent.user_id == user.id, AIUsageEvent.created_at >= since).count()
    if used >= int(limit):
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")


@router.post("/chat", response_model=ChatResponse)
def ai_chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_project_access(db, req.project_id, user)

    provider, api_key, api_base, default_model = _provider_settings(db)
    selected_model = req.model or default_model
    _enforce_ai_rate_limit(db, user)

    total_user_content_chars = sum(len(str(msg.get("content", ""))) for msg in req.messages if msg.get("role") == "user")
    if total_user_content_chars > 4000:
        raise HTTPException(status_code=400, detail="AI user content exceeds 4000 characters")

    scrubbed_messages = []
    total_redactions = 0
    prompt_chars = 0
    for msg in req.messages:
        clean_msg = {}
        for field_key, field_val in msg.items():
            if field_key == "content" and isinstance(field_val, str) and field_val:
                clean, count = scrub_text(field_val)
                total_redactions += count
                prompt_chars += len(clean)
                clean_msg[field_key] = clean
            elif isinstance(field_val, str) and field_val:
                clean, count = scrub_text(field_val)
                total_redactions += count
                clean_msg[field_key] = clean
            else:
                clean_msg[field_key] = field_val
        scrubbed_messages.append(clean_msg)

    if total_redactions > 0:
        log_action(db, req.project_id, "phi_redacted", {"redaction_count": total_redactions, "source": "ai_chat"})
    if not api_key and provider != "local":
        _record_ai_usage(db, user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=prompt_chars, status="not_configured")
        raise HTTPException(status_code=503, detail=f"{provider.upper()}_API_KEY not configured")

    try:
        resp = _llm_completion(provider, api_key, api_base, selected_model, scrubbed_messages)
        content = resp.choices[0].message.content
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    _record_ai_usage(db, user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=prompt_chars, completion_chars=len(content), status="ok")
    return ChatResponse(content=content, phi_redacted=total_redactions > 0, redaction_count=total_redactions)


@router.post("/intake-prefill", response_model=IntakePrefillResponse)
def intake_prefill(req: IntakePrefillRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_project_access(db, req.project_id, user)

    clean_description, redaction_count = scrub_text(req.description)
    if redaction_count > 0:
        log_action(db, req.project_id, "phi_redacted", {"redaction_count": redaction_count, "source": "intake_prefill"})
    provider, api_key, api_base, default_model = _provider_settings(db)
    if not api_key and provider != "local":
        raise HTTPException(status_code=503, detail=f"{provider.upper()}_API_KEY not configured")

    selected_model = default_model
    prompt = (
        "Return JSON only with optional keys q2, q3, q4, q5, q6, q7 for this QI project. "
        "Use canonical answer text when confident. q7 may be {\"description\":\"...\",\"date\":\"YYYY-MM-DD\"}. "
        "Known short labels are acceptable only for q2/q3 and will be normalized. "
        f"Project description: {clean_description}"
    )
    try:
        resp = _llm_completion(provider, api_key, api_base, selected_model, [{"role": "user", "content": prompt}])
        content = resp.choices[0].message.content
    except Exception:
        db.add(AIUsageEvent(user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=len(clean_description), completion_chars=0, status="error"))
        db.commit()
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))
    draft = _IntakePrefillDraft.model_validate(_extract_json_object(content)).model_dump(exclude_none=True)
    answers, _ = validate_answers(draft, drop_unmatched=True)
    return IntakePrefillResponse(answers=answers, phi_redacted=redaction_count > 0, redaction_count=redaction_count)


@router.post("/scrub-preview", response_model=ScrubPreviewResponse)
def scrub_preview(req: ScrubPreviewRequest, user: User = Depends(get_current_user)):
    """Local, non-LLM PHI check for chat input: lets the frontend show a redacted
    preview and require a second explicit send before anything reaches the AI."""
    clean, count = scrub_text(req.text)
    return ScrubPreviewResponse(text=clean, redacted=count > 0, count=count)


def _latest_active_upload(db: Session, project_id: int) -> Upload | None:
    return (
        db.query(Upload)
        .filter(Upload.project_id == project_id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )


_CLARIFY_SYSTEM_PROMPT = """You are helping a medical resident (not a statistician) clarify a quality-improvement (QI) project definition before analysis. You NEVER see raw patient data values -- only column names, column types, and the data dictionary text below. Do not ask the resident for patient names, MRNs, or other identifying information.

Project title (current): {title}
Project description (current): {description}
Dataset columns and types: {col_types}
Data dictionary: {dictionary_text}

Your job this turn:
- If the conversation is just starting, restate your understanding of the project and propose an improved, more specific title and description based on the context above.
- Identify the aim, intervention (if any), population, primary outcome, secondary outcomes, comparison, and time structure.
- Ask ONE targeted follow-up question at a time for anything vague or missing. Only ask about an intervention date if there is an intervention.
- Only set "confirmed" to true once you and the resident have reached a specific, complete project definition covering at minimum the aim, primary outcome, and time structure.

Respond with JSON only, no prose outside the JSON, in exactly this shape:
{{"message": "<your reply to the resident>", "reasoning": "<one or two sentences of your reasoning for this turn>", "suggested_title": "<string or null>", "suggested_description": "<string or null>", "confirmed": <true or false>, "design": {{"aim": "...", "intervention": "... or null", "population": "...", "primary_outcome": "...", "secondary_outcomes": ["..."], "comparison": "...", "time_structure": "..."}}}}"""


class _ClarifyDraft(BaseModel):
    message: str = ""
    reasoning: str | None = None
    suggested_title: str | None = None
    suggested_description: str | None = None
    confirmed: bool = False
    design: dict[str, Any] = {}

    model_config = ConfigDict(extra="ignore")


@router.post("/clarify/{project_id}", response_model=ClarifyResponse)
def ai_clarify(project_id: int, req: ClarifyRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _require_project_access(db, project_id, user)

    state = json.loads(project.ai_clarification_state) if project.ai_clarification_state else {"turns": [], "confirmed": False}
    turns = state.get("turns", [])

    if req.confirm:
        # Resident explicitly accepted the AI's rewrite -- that acceptance is itself
        # the resident's sign-off, so it confirms deterministically without another
        # LLM round-trip (which could second-guess an already-made decision).
        project.ai_clarification_state = json.dumps({"turns": turns, "confirmed": True})
        db.commit()
        last_ai_turn = next((t for t in reversed(turns) if t["role"] == "ai"), {})
        return ClarifyResponse(
            message=last_ai_turn.get("content", ""),
            reasoning=last_ai_turn.get("reasoning"),
            confirmed=True,
            turns=turns,
        )

    _enforce_ai_rate_limit(db, user)

    provider, api_key, api_base, default_model = _provider_settings(db)
    if not api_key and provider != "local":
        raise HTTPException(status_code=503, detail=f"{provider.upper()}_API_KEY not configured")

    clean_message = None
    redaction_count = 0
    if req.message:
        clean_message, redaction_count = scrub_text(req.message)
        if redaction_count > 0:
            log_action(db, project_id, "phi_redacted", {"redaction_count": redaction_count, "source": "ai_clarify"})
        turns.append({"role": "user", "content": clean_message})

    upload = _latest_active_upload(db, project_id)
    col_types = json.loads(upload.col_types) if upload and upload.col_types else {}
    dictionary_text = (upload.dictionary_text if upload else None) or "(none provided)"

    system_prompt = _CLARIFY_SYSTEM_PROMPT.format(
        title=project.title or "(untitled)",
        description=project.description or "(no description yet)",
        col_types=json.dumps(col_types),
        dictionary_text=dictionary_text,
    )
    messages = [{"role": "system", "content": system_prompt}]
    for turn in turns:
        messages.append({"role": "assistant" if turn["role"] == "ai" else "user", "content": turn["content"]})
    if not turns:
        messages.append({"role": "user", "content": "(starting the conversation -- please open with your understanding of the project)"})

    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        resp = _llm_completion(provider, api_key, api_base, default_model, messages, max_tokens=1500, reasoning_effort="low")
        content = resp.choices[0].message.content
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    draft = _ClarifyDraft.model_validate(_extract_json_object(content))
    turns.append({"role": "ai", "content": draft.message, "reasoning": draft.reasoning})

    project.ai_clarification_state = json.dumps({"turns": turns, "confirmed": draft.confirmed})
    if draft.design:
        existing_design = json.loads(project.ai_project_design) if project.ai_project_design else {}
        existing_design.update({k: v for k, v in draft.design.items() if v not in (None, "", [])})
        project.ai_project_design = json.dumps(existing_design)
    db.commit()

    _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, completion_chars=len(content), status="ok")

    return ClarifyResponse(
        message=draft.message,
        reasoning=draft.reasoning,
        suggested_title=draft.suggested_title,
        suggested_description=draft.suggested_description,
        confirmed=draft.confirmed,
        turns=turns,
    )


def _method_library_text() -> str:
    lines = []
    for template in ANALYSIS_TEMPLATES:
        model = TEMPLATE_PARAM_MODELS[template]
        fields = ", ".join(
            f"{name}{'' if field.is_required() else ' (optional)'}"
            for name, field in model.model_fields.items()
        )
        lines.append(f"- {template}: {ANALYSIS_DESCRIPTIONS[template]} Parameters: {fields}.")
    return "\n".join(lines)


_RECOMMEND_SYSTEM_PROMPT = """You are recommending a complete statistical analysis plan for a medical resident's quality-improvement (QI) project. You may recommend and combine multiple analyses -- never force a single choice -- but ONLY from this fixed library of implemented, executable methods (never propose anything outside this list, never invent a new method):

{method_library}

Confirmed project design: {design}
Dataset columns and types: {col_types}
Data dictionary: {dictionary_text}

Your job this turn:
- Recommend every analysis from the library above that is genuinely relevant given the project design (e.g. a pre/post project may need descriptive_summary AND run_chart AND before_after_mean together; a simple one-period project may need only descriptive_summary).
- For each recommended analysis, infer its exact parameters (real column names from the dataset above) as confidently as you can. Leave a parameter out only if you genuinely cannot infer it.
- Briefly explain why each analysis is recommended and what question it answers.
- If the resident denies an analysis or asks for something different, adjust the plan and explain the change.
- Only set "confirmed" to true once the resident has explicitly agreed to the final plan.

Respond with JSON only, no prose outside the JSON, in exactly this shape:
{{"message": "<your reply to the resident>", "reasoning": "<one or two sentences of your reasoning for this turn>", "confirmed": <true or false>, "analyses": [{{"template": "<one of the library ids above>", "rationale": "<why this analysis, briefly>", "parameters": {{"<param name>": "<inferred column name or value>"}}}}]}}"""


class _AnalysisPlanItemDraft(BaseModel):
    template: str
    rationale: str | None = None
    parameters: dict[str, Any] = {}

    model_config = ConfigDict(extra="ignore")


class _AnalysisPlanDraft(BaseModel):
    message: str = ""
    reasoning: str | None = None
    confirmed: bool = False
    analyses: list[_AnalysisPlanItemDraft] = []

    model_config = ConfigDict(extra="ignore")


@router.post("/recommend-plan/{project_id}", response_model=AnalysisPlanResponse)
def ai_recommend_plan(project_id: int, req: AnalysisPlanRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _require_project_access(db, project_id, user)
    _enforce_ai_rate_limit(db, user)

    provider, api_key, api_base, default_model = _provider_settings(db)
    if not api_key and provider != "local":
        raise HTTPException(status_code=503, detail=f"{provider.upper()}_API_KEY not configured")

    state = json.loads(project.ai_analysis_plan) if project.ai_analysis_plan else {}
    turns = state.get("turns", [])

    clean_message = None
    redaction_count = 0
    if req.message:
        clean_message, redaction_count = scrub_text(req.message)
        if redaction_count > 0:
            log_action(db, project_id, "phi_redacted", {"redaction_count": redaction_count, "source": "ai_recommend_plan"})
        turns.append({"role": "user", "content": clean_message})

    upload = _latest_active_upload(db, project_id)
    col_types = json.loads(upload.col_types) if upload and upload.col_types else {}
    dictionary_text = (upload.dictionary_text if upload else None) or "(none provided)"
    design = json.loads(project.ai_project_design) if project.ai_project_design else {}

    system_prompt = _RECOMMEND_SYSTEM_PROMPT.format(
        method_library=_method_library_text(),
        design=json.dumps(design) if design else "(not yet clarified)",
        col_types=json.dumps(col_types),
        dictionary_text=dictionary_text,
    )
    messages = [{"role": "system", "content": system_prompt}]
    for turn in turns:
        messages.append({"role": "assistant" if turn["role"] == "ai" else "user", "content": turn["content"]})
    if not turns:
        messages.append({"role": "user", "content": "(starting the conversation -- please propose your recommended analysis plan)"})

    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        resp = _llm_completion(provider, api_key, api_base, default_model, messages, max_tokens=1500, reasoning_effort="low")
        content = resp.choices[0].message.content
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    draft = _AnalysisPlanDraft.model_validate(_extract_json_object(content))
    analyses = [a.model_dump() for a in draft.analyses if a.template in ANALYSIS_TEMPLATES]
    turns.append({"role": "ai", "content": draft.message, "reasoning": draft.reasoning})

    project.ai_analysis_plan = json.dumps({"turns": turns, "confirmed": draft.confirmed, "analyses": analyses})
    db.commit()

    _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, completion_chars=len(content), status="ok")

    return AnalysisPlanResponse(
        message=draft.message,
        reasoning=draft.reasoning,
        confirmed=draft.confirmed,
        analyses=analyses,
        turns=turns,
    )
