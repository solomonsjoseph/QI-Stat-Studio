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
from api.models_api import ChatRequest, ChatResponse, IntakePrefillRequest, IntakePrefillResponse
from api.audit import log_action, safe_diagnostic_message
from api.models_db import AIUsageEvent, Project, User
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
    "openai": "",
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


def _llm_completion(provider: str, api_key: str | None, api_base: str | None, model: str, messages: list[dict[str, str]]):
    """Route a chat completion through litellm's unified, OpenAI-compatible interface."""
    kwargs: dict[str, Any] = {
        "model": f"{_MODEL_PREFIXES[provider]}{model}",
        "messages": messages,
        "max_tokens": 800,
        "timeout": 30,
        "num_retries": 2,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
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

@router.post("/chat", response_model=ChatResponse)
def ai_chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_project_access(db, req.project_id, user)

    provider, api_key, api_base, default_model = _provider_settings(db)
    selected_model = req.model or default_model
    limit = get_runtime_setting(db, "ai_rate_limit_per_hour") or 20
    since = datetime.utcnow() - timedelta(hours=1)
    used = db.query(AIUsageEvent).filter(AIUsageEvent.user_id == user.id, AIUsageEvent.created_at >= since).count()
    if used >= int(limit):
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")

    total_user_content_chars = sum(len(str(msg.get("content", ""))) for msg in req.messages if msg.get("role") == "user")
    if total_user_content_chars > 4000:
        raise HTTPException(status_code=400, detail="AI user content exceeds 4000 characters")

    scrubbed_messages = []
    total_redactions = 0
    prompt_chars = 0
    for msg in req.messages:
        content = msg.get("content")
        if isinstance(content, str) and content:
            clean, count = scrub_text(content)
            total_redactions += count
            prompt_chars += len(clean)
            scrubbed_messages.append({**msg, "content": clean})
        else:
            if isinstance(content, str):
                prompt_chars += len(content)
            scrubbed_messages.append(msg)

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
