from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

import litellm
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from api.ai_prompts import (
    CLARIFY_SYSTEM_V1,
    COLLECTION_SYSTEM_V1,
    INTERPRET_SYSTEM_V1,
    OVERRIDE_SYSTEM_V1,
    PROMPT_VERSIONS,
    RECOMMEND_SYSTEM_V1,
)
from api.dataset_profile import get_upload_profile
from api.models_api import (
    AnalysisPlanItem,
    AnalysisPlanRequest,
    AnalysisPlanResponse,
    ChatRequest,
    ChatResponse,
    ClarifyRequest,
    ClarifyResponse,
    InterpretResultsResponse,
    OverridePlanRequest,
    OverridePlanResponse,
    ProjectDesign,
    RecommendPlanModel,
    RunInterpretation,
    ScrubPreviewRequest,
    ScrubPreviewResponse,
)
from api.routers.projects import advance_phase, require_phase
from api.routers.analyze import check_plan_item
from api.project_design import DESIGN_FIELDS, get_field_value, merge_ai_design

from api.auth import get_current_user
from api.config import settings
from api.database import get_db
from api.middleware.phi_scrubber import scrub_text
from api.analysis_schemas import TEMPLATE_PARAM_MODELS
from api.routers.analyze import _ALL as ANALYSIS_TEMPLATES
from api.routers.analyze import _DESCRIPTIONS as ANALYSIS_DESCRIPTIONS
from api.audit import log_action, safe_diagnostic_message
from api.models_db import AIUsageEvent, AnalysisRun, Project, Upload, User
from api.settings_registry import get_runtime_setting

router = APIRouter(prefix="/ai", tags=["ai"])



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


def _untrusted(text: str) -> str:
    return f"<untrusted_data>\n{text}\n</untrusted_data>"


_CAUSAL_CLAIM_RE = re.compile(
    r"\b(caused|causes|causing|proves?|demonstrates?\s+that|results?\s+in|led\s+to|due\s+to\s+the\s+intervention)\b",
    re.I,
)
_ABSOLUTE_NULL_CLAIM_RE = re.compile(
    r"\bno\s+(difference|effect|change|impact)\b(?!\s*that\s+(is|was)\s+statistically)",
    re.I,
)


def _flag_overstated_claims(text: str, p_values: list[float]) -> list[str]:
    """Deterministic backstop for the LLM's causal/significance-language instructions.

    Flags text for human review; never edits or blocks it. p_values >= 0.05
    means a non-significant result exists somewhere in the run set, so an
    unqualified "no difference/effect" claim is an overstatement worth a
    second look rather than a true null result.
    """
    flags = []
    if not text:
        return flags
    if _CAUSAL_CLAIM_RE.search(text):
        flags.append("Possible causal-language overstatement (QI projects should not claim causation).")
    if any(p is not None and p >= 0.05 for p in p_values) and _ABSOLUTE_NULL_CLAIM_RE.search(text):
        flags.append("Possible overstatement of a non-significant result as a definitive null finding.")
    return flags


_INTERVENTION_TOPIC_RE = re.compile(
    r"intervention\s+date|what\s+(change|intervention)|when\s+did\s+you\s+(implement|roll\s*out|introduce|start)|"
    r"\b(implement(ed|ation)?|roll(ed)?[\s-]?out|go[\s-]?live)\b.*\b(change|intervention)\b|"
    r"\b(change|intervention)\b.*\b(implement(ed)?|roll(ed)?[\s-]?out|start(ed)?|introduc(ed|e))\b",
    re.I,
)


def _drop_irrelevant_questions(message: str, design: ProjectDesign | None) -> str:
    if not message:
        return message

    drop_intervention = not (design and design.intervention and design.intervention.present)
    drop_pairing = not (design and design.pairing_id_column)

    lines = message.splitlines()
    kept_lines = []
    for line in lines:
        if drop_intervention and _INTERVENTION_TOPIC_RE.search(line):
            continue
        if drop_pairing and re.search(r"\b(paired|pairing)\b", line, re.I):
            continue
        kept_lines.append(line)

    result = "\n".join(kept_lines)
    if len(lines) <= 1 and ("." in message or "?" in message):
        sentences = re.split(r"(?<=[.?!])\s+", result)
        kept_sentences = []
        for s in sentences:
            if drop_intervention and _INTERVENTION_TOPIC_RE.search(s):
                continue
            if drop_pairing and re.search(r"\b(paired|pairing)\b", s, re.I):
                continue
            kept_sentences.append(s)
        result = " ".join(kept_sentences)

    return result.strip()


def _provider_settings(db: Session) -> tuple[str, str | None, str | None, str]:
    """Resolve (provider, api_key, api_base, default_model) for the configured AI provider."""
    provider = (get_runtime_setting(db, "ai_provider") or settings.ai_provider or "openrouter").strip().lower()
    if provider == "stub":
        return "stub", "stub", None, "stub"
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
    if provider == "stub":
        from api import ai_stub

        return ai_stub.canned_response(messages)
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


def _llm_completion_nonempty(
    provider: str,
    api_key: str | None,
    api_base: str | None,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    reasoning_effort: str | None,
) -> str:
    """Call the LLM and guarantee non-blank content.

    A reasoning model can spend its entire max_tokens budget on hidden reasoning
    and return empty content for anything beyond a trivial prompt -- this looked
    to the resident like the AI "stopped responding" (a blank turn silently
    appended to the conversation, no error, nothing to retry). Retry once with a
    lower reasoning effort and a larger budget; if it's still blank, raise so the
    caller shows a real error instead of persisting a dead turn.
    """
    resp = _llm_completion(provider, api_key, api_base, model, messages, max_tokens=max_tokens, reasoning_effort=reasoning_effort)
    content = (resp.choices[0].message.content or "").strip()
    if content:
        return content
    resp = _llm_completion(provider, api_key, api_base, model, messages, max_tokens=max_tokens * 2, reasoning_effort="minimal")
    content = (resp.choices[0].message.content or "").strip()
    if content:
        return content
    raise RuntimeError("empty_llm_response")


def _validated_completion(
    provider: str,
    api_key: str | None,
    api_base: str | None,
    model: str,
    messages: list[dict[str, str]],
    model_cls: type[Any],
    max_tokens: int = 1500,
    reasoning_effort: str | None = "low",
) -> Any:
    """Wrap _llm_completion_nonempty, parse JSON via _extract_json_object, validate into model_cls.

    On ValidationError or unparseable JSON, retries ONCE with an appended corrective user message
    quoting the validation error. On second failure raises HTTPException(502, safe_diagnostic_message('ai_invalid_response')).
    """
    content = _llm_completion_nonempty(
        provider, api_key, api_base, model, messages, max_tokens=max_tokens, reasoning_effort=reasoning_effort
    )
    try:
        data = _extract_json_object(content)
        if data:
            return model_cls.model_validate(data)
        err_msg = "Output was not valid JSON"
    except Exception as exc:
        err_msg = str(exc)

    corrective_msg = (
        f"Your previous response did not match the required JSON schema:\n{err_msg}\n"
        "Please respond with valid JSON matching the schema exactly, with no additional commentary."
    )
    retry_messages = list(messages) + [{"role": "user", "content": corrective_msg}]

    try:
        retry_content = _llm_completion_nonempty(
            provider, api_key, api_base, model, retry_messages, max_tokens=max_tokens, reasoning_effort="minimal"
        )
        retry_data = _extract_json_object(retry_content)
        if not retry_data:
            raise ValueError("Retry response was not valid JSON")
        return model_cls.model_validate(retry_data)
    except Exception:
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_invalid_response"))

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



@router.post("/scrub-preview", response_model=ScrubPreviewResponse)
def scrub_preview(req: ScrubPreviewRequest, user: User = Depends(get_current_user)):
    """Local, non-LLM PHI check for chat input: lets the frontend show a redacted
    preview and require a second explicit send before anything reaches the AI.
    Preserves dates (redact_dates=False), matching /ai/clarify's actual send -- an
    intervention start date is operationally relevant QI content, not PHI."""
    clean, count = scrub_text(req.text, redact_dates=False)
    return ScrubPreviewResponse(text=clean, redacted=count > 0, count=count)


def _latest_active_upload(db: Session, project_id: int) -> Upload | None:
    return (
        db.query(Upload)
        .filter(Upload.project_id == project_id, Upload.status == "active")
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .first()
    )


class ClarifyResponseModel(BaseModel):
    message: str = ""
    reasoning: str | None = None
    suggested_title: str | None = None
    suggested_description: str | None = None
    confirmed: bool = False
    sufficient_to_continue: bool = False
    design: ProjectDesign = Field(default_factory=ProjectDesign)

    model_config = ConfigDict(extra="ignore")

@router.post("/clarify/{project_id}", response_model=ClarifyResponse)
def ai_clarify(project_id: int, req: ClarifyRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _require_project_access(db, project_id, user)
    require_phase(db, project, "clarify")

    state = json.loads(project.ai_clarification_state) if project.ai_clarification_state else {"turns": [], "confirmed": False}
    turns = state.get("turns", [])

    if req.confirm:
        project.ai_clarification_state = json.dumps({"turns": turns, "confirmed": True})
        advance_phase(db, project, "review")
        if project.ai_project_design:
            try:
                d_dict = json.loads(project.ai_project_design)
                status_map = d_dict.setdefault("status", {})
                for path in DESIGN_FIELDS:
                    val = get_field_value(d_dict, path)
                    if val not in (None, "", False, {}):
                        if status_map.get(path) != "user-corrected":
                            status_map[path] = "user-confirmed"
                project.ai_project_design = json.dumps(d_dict)
            except Exception:
                pass
        db.commit()
        last_ai_turn = next((t for t in reversed(turns) if t["role"] == "ai"), {})
        return ClarifyResponse(
            message=last_ai_turn.get("content", ""),
            reasoning=last_ai_turn.get("reasoning"),
            confirmed=True,
            turns=turns,
            design=json.loads(project.ai_project_design) if project.ai_project_design else None,
        )

    _enforce_ai_rate_limit(db, user)

    provider, api_key, api_base, default_model = _provider_settings(db)
    if not api_key and provider != "local":
        raise HTTPException(status_code=503, detail=f"{provider.upper()}_API_KEY not configured")

    clean_message = None
    redaction_count = 0
    if req.message:
        clean_message, redaction_count = scrub_text(req.message, redact_dates=False)
        if redaction_count > 0:
            log_action(db, project_id, "phi_redacted", {"redaction_count": redaction_count, "source": "ai_clarify"})
        turns.append({"role": "user", "content": clean_message})

    upload = _latest_active_upload(db, project_id)
    profile = get_upload_profile(upload) if upload else {}
    profile_json = json.dumps(profile, indent=2)
    dictionary_text = (upload.dictionary_text if upload else None) or "(none provided)"
    dictionary_text_truncated, _ = scrub_text(dictionary_text[:4000])

    system_prompt = CLARIFY_SYSTEM_V1.format(
        title=project.title or "(untitled)",
        description=project.description or "(no description yet)",
        dataset_profile=_untrusted(profile_json),
        dictionary_text=_untrusted(dictionary_text_truncated),
    )
    messages = [{"role": "system", "content": system_prompt}]
    for turn in turns:
        messages.append({"role": "assistant" if turn["role"] == "ai" else "user", "content": turn["content"]})
    if not turns:
        messages.append({"role": "user", "content": "(starting the conversation -- please open with your understanding of the project)"})

    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        resp_model: ClarifyResponseModel = _validated_completion(
            provider, api_key, api_base, default_model, messages, ClarifyResponseModel, max_tokens=1500
        )
    except HTTPException:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    cleaned_message = _drop_irrelevant_questions(resp_model.message, resp_model.design)
    if not cleaned_message:
        cleaned_message = "Could you tell me more about what you are aiming to improve?"

    turns.append({"role": "ai", "content": cleaned_message, "reasoning": resp_model.reasoning})
    project.ai_clarification_state = json.dumps({"turns": turns, "confirmed": resp_model.confirmed})

    existing_design_dict = json.loads(project.ai_project_design or "{}") if project.ai_project_design else {}
    merged_design = merge_ai_design(resp_model.design, existing_design_dict)
    project.ai_project_design = json.dumps(merged_design.model_dump())
    db.commit()

    _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, completion_chars=len(cleaned_message), status="ok")

    return ClarifyResponse(
        message=cleaned_message,
        reasoning=resp_model.reasoning,
        suggested_title=resp_model.suggested_title,
        suggested_description=resp_model.suggested_description,
        confirmed=resp_model.confirmed,
        turns=turns,
        design=merged_design.model_dump(),
    )


@router.post("/collection-guidance/{project_id}")
def ai_collection_guidance(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _require_project_access(db, project_id, user)
    require_phase(db, project, "clarify")
    design_dict = json.loads(project.ai_project_design or "{}")
    design = ProjectDesign.model_validate(design_dict)

    upload = _latest_active_upload(db, project_id)
    if not upload:
        return {"recommendations": [], "generated_at": datetime.utcnow().isoformat()}

    from api.collection_guidance import deterministic_recommendations
    from api.upload_utils import load_upload_dataframe

    try:
        df = load_upload_dataframe(upload)
    except Exception:
        df = pd.DataFrame()

    profile = get_upload_profile(upload)
    rules_recs = deterministic_recommendations(design, df, profile)

    ai_recs: list[dict[str, Any]] = []
    provider, api_key, api_base, default_model = _provider_settings(db)
    if api_key or provider == "local":
        try:
            _enforce_ai_rate_limit(db, user)
            system_prompt = COLLECTION_SYSTEM_V1.format(
                design=_untrusted(json.dumps(design.model_dump(), indent=2)),
                dataset_profile=_untrusted(json.dumps(profile, indent=2)),
                dictionary_text=_untrusted(scrub_text((upload.dictionary_text or "(none)")[:4000])[0]),
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Review project design and profile for collection recommendations."},
            ]
            prompt_chars = sum(len(m["content"]) for m in messages)
            content = _llm_completion_nonempty(
                provider, api_key, api_base, default_model, messages, max_tokens=1000, reasoning_effort="low"
            )
            parsed = _extract_json_object(content)
            raw_ai_items = parsed.get("recommendations", [])
            rule_ids = {r["id"] for r in rules_recs}
            for item in raw_ai_items:
                if isinstance(item, dict) and item.get("id") and item.get("id") not in rule_ids:
                    item["source"] = "ai"
                    ai_recs.append(item)
            _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, completion_chars=len(content), status="ok")
        except Exception:
            pass

    combined = rules_recs + ai_recs
    now_iso = datetime.utcnow().isoformat()
    project.data_collection_notes = json.dumps({"recommendations": combined, "generated_at": now_iso})
    db.commit()

    return {"recommendations": combined, "generated_at": now_iso}

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


@router.post("/recommend-plan/{project_id}", response_model=AnalysisPlanResponse)
def ai_recommend_plan(project_id: int, req: AnalysisPlanRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _require_project_access(db, project_id, user)
    require_phase(db, project, "plan")

    if req.confirm:
        # Resident's explicit confirmation of the (possibly edited) plan is itself
        # the sign-off -- persist deterministically, no LLM round-trip.
        upload = _latest_active_upload(db, project_id)
        from api.upload_utils import load_upload_dataframe
        try:
            df = load_upload_dataframe(upload) if upload else pd.DataFrame()
        except Exception:
            df = pd.DataFrame()

        confirmed_analyses: list[AnalysisPlanItem] = []
        for idx, item_dict in enumerate(req.analyses or []):
            item = AnalysisPlanItem.model_validate(item_dict)
            if not item.id:
                item.id = f"{item.template}-{idx + 1}"
            check = check_plan_item(db, project, upload, df, item.template, item.parameters)
            item.executable = check["ok"]
            item.errors = check["errors"]
            item.missing_params = check["missing_params"]
            item.parameters = check["parameters"]
            confirmed_analyses.append(item)

        state = json.loads(project.ai_analysis_plan) if project.ai_analysis_plan else {}
        turns = state.get("turns", [])
        project.ai_analysis_plan = json.dumps({
            "turns": turns,
            "confirmed": True,
            "analyses": [a.model_dump() for a in confirmed_analyses],
            "stale": False,
        })
        db.commit()
        return AnalysisPlanResponse(
            message="Plan confirmed.",
            reasoning=None,
            confirmed=True,
            analyses=confirmed_analyses,
            turns=turns,
        )

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
    profile = get_upload_profile(upload) if upload else {}
    profile_json = json.dumps(profile, indent=2)
    quality_flags_raw = json.loads(upload.quality_flags) if upload and upload.quality_flags else []
    quality_findings, _ = scrub_text(json.dumps(quality_flags_raw, indent=2))
    dictionary_text = (upload.dictionary_text if upload else None) or "(none provided)"
    dictionary_text_truncated, _ = scrub_text(dictionary_text[:4000])
    design = json.loads(project.ai_project_design) if project.ai_project_design else {}

    system_prompt = RECOMMEND_SYSTEM_V1.format(
        method_library=_method_library_text(),
        design=_untrusted(json.dumps(design, indent=2)),
        dataset_profile=_untrusted(profile_json),
        quality_findings=_untrusted(quality_findings),
        dictionary_text=_untrusted(dictionary_text_truncated),
    )
    messages = [{"role": "system", "content": system_prompt}]
    for turn in turns:
        messages.append({"role": "assistant" if turn["role"] == "ai" else "user", "content": turn["content"]})
    if not turns:
        messages.append({"role": "user", "content": "(starting the conversation -- please propose your recommended analysis plan)"})

    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        resp_model: RecommendPlanModel = _validated_completion(
            provider, api_key, api_base, default_model, messages, RecommendPlanModel, max_tokens=2000
        )
    except HTTPException:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    from api.upload_utils import load_upload_dataframe
    try:
        df = load_upload_dataframe(upload) if upload else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()

    validated_analyses: list[AnalysisPlanItem] = []
    for idx, item in enumerate(resp_model.analyses):
        if item.template not in ANALYSIS_TEMPLATES:
            continue
        if not item.id:
            item.id = f"{item.template}-{idx + 1}"
        check = check_plan_item(db, project, upload, df, item.template, item.parameters)
        item.executable = check["ok"]
        item.errors = check["errors"]
        item.missing_params = check["missing_params"]
        item.parameters = check["parameters"]
        item.needs_clarification = any(c == "low" for c in item.param_confidence.values()) or bool(item.missing_params)
        validated_analyses.append(item)

    turns.append({"role": "ai", "content": resp_model.message, "reasoning": resp_model.reasoning})

    # Initial plan history written once
    if not project.ai_plan_history:
        project.ai_plan_history = json.dumps({
            "initial": [a.model_dump() for a in validated_analyses],
            "overrides": [],
            "revised": [],
        })

    project.ai_analysis_plan = json.dumps({
        "turns": turns,
        "confirmed": resp_model.confirmed,
        "analyses": [a.model_dump() for a in validated_analyses],
        "stale": False,
    })
    db.commit()

    _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, completion_chars=len(resp_model.message), status="ok")

    return AnalysisPlanResponse(
        message=resp_model.message,
        reasoning=resp_model.reasoning,
        confirmed=resp_model.confirmed,
        analyses=validated_analyses,
        turns=turns,
    )


@router.post("/override-plan/{project_id}", response_model=OverridePlanResponse)
def ai_override_plan(
    project_id: int,
    body: OverridePlanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _require_project_access(db, project_id, user)
    require_phase(db, project, "plan")
    _enforce_ai_rate_limit(db, user)

    provider, api_key, api_base, default_model = _provider_settings(db)
    if not api_key and provider != "local":
        raise HTTPException(status_code=503, detail=f"{provider.upper()}_API_KEY not configured")

    clean_instruction, redaction_count = scrub_text(body.instruction)
    if redaction_count > 0:
        log_action(db, project_id, "phi_redacted", {"redaction_count": redaction_count, "source": "ai_override_plan"})

    upload = _latest_active_upload(db, project_id)
    profile = get_upload_profile(upload) if upload else {}
    profile_json = json.dumps(profile, indent=2)
    design = json.loads(project.ai_project_design) if project.ai_project_design else {}
    current_plan = json.loads(project.ai_analysis_plan) if project.ai_analysis_plan else {}

    system_prompt = OVERRIDE_SYSTEM_V1.format(
        method_library=_method_library_text(),
        design=_untrusted(json.dumps(design, indent=2)),
        dataset_profile=_untrusted(profile_json),
        current_plan=_untrusted(json.dumps(current_plan.get("analyses", []), indent=2)),
        instruction=_untrusted(clean_instruction),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Please revise the plan according to this instruction: {clean_instruction}"},
    ]

    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        resp_model: OverridePlanResponse = _validated_completion(
            provider, api_key, api_base, default_model, messages, OverridePlanResponse, max_tokens=2000
        )
    except HTTPException:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    from api.upload_utils import load_upload_dataframe
    try:
        df = load_upload_dataframe(upload) if upload else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()

    validated_analyses: list[AnalysisPlanItem] = []
    for idx, item in enumerate(resp_model.analyses):
        if item.template not in ANALYSIS_TEMPLATES:
            continue
        if not item.id:
            item.id = f"{item.template}-{idx + 1}"
        check = check_plan_item(db, project, upload, df, item.template, item.parameters)
        item.executable = check["ok"]
        item.errors = check["errors"]
        item.missing_params = check["missing_params"]
        item.parameters = check["parameters"]
        item.needs_clarification = any(c == "low" for c in item.param_confidence.values()) or bool(item.missing_params)
        validated_analyses.append(item)

    # Append to overrides in history
    history = json.loads(project.ai_plan_history or "{}") if project.ai_plan_history else {"initial": [], "overrides": [], "revised": []}
    history.setdefault("overrides", []).append({
        "instruction": clean_instruction,
        "changes": resp_model.changes,
        "analyses": [a.model_dump() for a in validated_analyses],
        "timestamp": datetime.utcnow().isoformat(),
    })
    project.ai_plan_history = json.dumps(history)

    # Reset confirmed flag on plan so resident re-confirms
    current_plan["analyses"] = [a.model_dump() for a in validated_analyses]
    current_plan["confirmed"] = False
    current_plan["stale"] = False
    project.ai_analysis_plan = json.dumps(current_plan)
    db.commit()

    _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, completion_chars=len(resp_model.message), status="ok")

    return OverridePlanResponse(
        message=resp_model.message,
        changes=resp_model.changes,
        confirmed=False,
        analyses=validated_analyses,
    )


@router.post("/interpret-results/{project_id}", response_model=InterpretResultsResponse)
def ai_interpret_results(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _require_project_access(db, project_id, user)
    require_phase(db, project, "results")
    _enforce_ai_rate_limit(db, user)

    provider, api_key, api_base, default_model = _provider_settings(db)
    if not api_key and provider != "local":
        raise HTTPException(status_code=503, detail=f"{provider.upper()}_API_KEY not configured")

    upload = _latest_active_upload(db, project_id)
    if not upload:
        raise HTTPException(404, "No active upload found")

    runs = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.project_id == project_id, AnalysisRun.upload_id == upload.id)
        .order_by(AnalysisRun.created_at.asc(), AnalysisRun.id.asc())
        .all()
    )
    if not runs:
        raise HTTPException(400, "No analysis runs found for project")

    _INTERPRET_FIELDS = (
        "template", "result_summary", "p_value", "test_used", "effect_estimate",
        "effect_ci", "odds_ratio", "risk_difference", "ucl", "lcl", "pbar",
        "signal_detected", "trend_signal_detected", "n_pairs",
    )
    results_payload = []
    for run in runs:
        res_json = json.loads(run.result_json or "{}")
        run_data = {k: res_json.get(k) for k in _INTERPRET_FIELDS if res_json.get(k) is not None}
        run_data["run_id"] = run.id
        run_data["template"] = run.template
        results_payload.append(run_data)

    ack_flags = json.loads(upload.acknowledged_flags or "[]")
    ack_text, _ = scrub_text(json.dumps(ack_flags, indent=2))

    system_prompt = INTERPRET_SYSTEM_V1.format(
        results_payload=_untrusted(json.dumps(results_payload, indent=2)),
        acknowledged_warnings=_untrusted(ack_text),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Please provide interpretations, limitations, and an abstract draft for these analysis results."},
    ]

    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        resp_model: InterpretResultsResponse = _validated_completion(
            provider, api_key, api_base, default_model, messages, InterpretResultsResponse, max_tokens=2500
        )
    except HTTPException:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    p_values = [rd.get("p_value") for rd in results_payload if isinstance(rd.get("p_value"), (int, float))]
    flags: list[str] = []
    for interp in resp_model.interpretations:
        flags.extend(_flag_overstated_claims(interp.text, p_values))
    flags.extend(_flag_overstated_claims(resp_model.abstract_draft, p_values))
    resp_model.needs_review_flags = flags

    # Persist interpretations onto runs
    for interp in resp_model.interpretations:
        r_obj = next((r for r in runs if r.id == interp.run_id), None)
        if r_obj:
            r_dict = json.loads(r_obj.result_json or "{}")
            r_dict["ai_interpretation"] = interp.text
            r_obj.result_json = json.dumps(r_dict)

    # Persist narrative onto project plan
    plan_dict = json.loads(project.ai_analysis_plan or "{}")
    plan_dict["narrative"] = {
        "limitations": resp_model.limitations,
        "abstract_draft": resp_model.abstract_draft,
        "needs_review_flags": resp_model.needs_review_flags,
    }
    project.ai_analysis_plan = json.dumps(plan_dict)
    db.commit()

    _record_ai_usage(db, user_id=user.id, project_id=project_id, model=default_model, prompt_chars=prompt_chars, completion_chars=len(resp_model.abstract_draft), status="ok")

    return resp_model
