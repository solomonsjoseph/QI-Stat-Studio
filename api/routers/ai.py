import json
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from api.database import get_db
from api.middleware.phi_scrubber import scrub_text
from api.models_db import AuditLog
from api.config import settings

router = APIRouter(prefix="/ai", tags=["ai"])


class ChatRequest(BaseModel):
    project_id: int
    messages: list  # [{"role": "user"|"assistant", "content": str}]
    model: str = "openai/gpt-4o-mini"


class ChatResponse(BaseModel):
    content: str
    phi_redacted: bool
    redaction_count: int


@router.post("/chat", response_model=ChatResponse)
def ai_chat(req: ChatRequest, db: Session = Depends(get_db)):
    # Scrub all user messages for PHI
    scrubbed_messages = []
    total_redactions = 0
    for msg in req.messages:
        if msg.get("role") == "user":
            clean, count = scrub_text(msg["content"])
            total_redactions += count
            scrubbed_messages.append({"role": "user", "content": clean})
        else:
            scrubbed_messages.append(msg)

    if total_redactions > 0:
        db.add(AuditLog(
            project_id=req.project_id,
            action="phi_redacted",
            metadata_json=json.dumps({"redaction_count": total_redactions}),
        ))
        db.commit()

    api_key = getattr(settings, "openrouter_api_key", None)
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY not configured")

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": req.model, "messages": scrubbed_messages},
        timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"OpenRouter error: {resp.text[:200]}")

    content = resp.json()["choices"][0]["message"]["content"]
    return ChatResponse(content=content, phi_redacted=total_redactions > 0, redaction_count=total_redactions)
