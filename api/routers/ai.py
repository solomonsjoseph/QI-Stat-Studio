from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
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



def _openrouter_post(api_key: str, model: str, messages: list[dict[str, str]]) -> httpx.Response:
    payload = {"model": model, "messages": messages, "max_tokens": 800}
    last_response: httpx.Response | None = None
    for attempt in range(3):
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        last_response = resp
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < 2:
                time.sleep(0.05 * (2**attempt))
                continue
        return resp
    assert last_response is not None
    return last_response


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

    selected_model = req.model or get_runtime_setting(db, "openrouter_model") or settings.openrouter_model
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
        content = str(msg.get("content", ""))
        if msg.get("role") == "user":
            clean, count = scrub_text(content)
            total_redactions += count
            prompt_chars += len(clean)
            scrubbed_messages.append({"role": "user", "content": clean})
        else:
            prompt_chars += len(content)
            scrubbed_messages.append(msg)

    if total_redactions > 0:
        log_action(db, req.project_id, "phi_redacted", {"redaction_count": total_redactions, "source": "ai_chat"})
    api_key = getattr(settings, "openrouter_api_key", None)
    if not api_key:
        _record_ai_usage(db, user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=prompt_chars, status="not_configured")
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY not configured")

    try:
        resp = _openrouter_post(api_key, selected_model, scrubbed_messages)
    except Exception:
        _record_ai_usage(db, user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    if resp.status_code != 200:
        _record_ai_usage(db, user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=prompt_chars, status="error")
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    try:
        content = resp.json()["choices"][0]["message"]["content"]
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
    api_key = getattr(settings, "openrouter_api_key", None)
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY not configured")

    selected_model = get_runtime_setting(db, "openrouter_model") or settings.openrouter_model
    prompt = (
        "Return JSON only with optional keys q2, q3, q4, q5, q6, q7 for this QI project. "
        "Use canonical answer text when confident. q7 may be {\"description\":\"...\",\"date\":\"YYYY-MM-DD\"}. "
        "Known short labels are acceptable only for q2/q3 and will be normalized. "
        f"Project description: {clean_description}"
    )
    try:
        resp = _openrouter_post(api_key, selected_model, [{"role": "user", "content": prompt}])
    except Exception:
        db.add(AIUsageEvent(user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=len(clean_description), completion_chars=0, status="error"))
        db.commit()
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))
    if resp.status_code != 200:
        db.add(AIUsageEvent(user_id=user.id, project_id=req.project_id, model=selected_model, prompt_chars=len(clean_description), completion_chars=0, status="error"))
        db.commit()
        raise HTTPException(status_code=502, detail=safe_diagnostic_message("ai_service_unavailable"))

    content = resp.json()["choices"][0]["message"]["content"]
    draft = _IntakePrefillDraft.model_validate(_extract_json_object(content)).model_dump(exclude_none=True)
    answers, _ = validate_answers(draft, drop_unmatched=True)
    return IntakePrefillResponse(answers=answers, phi_redacted=redaction_count > 0, redaction_count=redaction_count)
