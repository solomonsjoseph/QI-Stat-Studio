"""Live list of the models a provider offers, fetched with the caller's own key.

Nothing here names a model. The list comes from the provider each time it is not cached, so new
models appear and retired ones disappear without a code change.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

import httpx
from fastapi import HTTPException

from api.models_api import ModelInfo

logger = logging.getLogger(__name__)

_TTL_SECONDS = 600
_TIMEOUT_SECONDS = 10
_cache: dict[tuple, tuple[float, list[ModelInfo]]] = {}

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/~@+-]{0,127}$")
_OPENAI_SKIP = ("audio", "realtime", "tts", "transcribe", "image", "embedding", "moderation", "search", "whisper", "dall-e", "davinci", "babbage")


def _get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = httpx.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _per_million(value: Any) -> float | None:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def _openrouter(payload: dict[str, Any]) -> list[ModelInfo]:
    out = []
    for item in payload.get("data", []):
        model_id = item.get("id", "")
        modalities = (item.get("architecture") or {}).get("output_modalities") or []
        if not model_id or "text" not in modalities or model_id.endswith(":batch"):
            continue
        pricing = item.get("pricing") or {}
        out.append(ModelInfo(
            id=model_id,
            name=item.get("name") or model_id,
            context_length=item.get("context_length"),
            prompt_price_per_million=_per_million(pricing.get("prompt")),
            completion_price_per_million=_per_million(pricing.get("completion")),
            reasoning="reasoning" in (item.get("supported_parameters") or []),
        ))
    return out


def _openai_style(payload: dict[str, Any], filter_names: bool) -> list[ModelInfo]:
    out = []
    for item in payload.get("data", []):
        model_id = item.get("id", "")
        if not model_id or (filter_names and any(word in model_id for word in _OPENAI_SKIP)):
            continue
        out.append(ModelInfo(id=model_id, name=model_id))
    return out


def _gemini(payload: dict[str, Any]) -> list[ModelInfo]:
    out = []
    for item in payload.get("models", []):
        if "generateContent" not in (item.get("supportedGenerationMethods") or []):
            continue
        model_id = str(item.get("name", "")).removeprefix("models/")
        if model_id:
            out.append(ModelInfo(id=model_id, name=item.get("displayName") or model_id, context_length=item.get("inputTokenLimit")))
    return out


def _request(provider: str, api_key: str | None, api_base: str | None) -> list[ModelInfo]:
    if provider == "openrouter":
        # With a key, the provider returns only models that account may use, and it rejects a bad key.
        path = "models/user" if api_key else "models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return _openrouter(_get(f"https://openrouter.ai/api/v1/{path}", headers))
    if provider == "openai":
        return _openai_style(_get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"}), True)
    if provider == "gemini":
        return _gemini(_get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": api_key or ""}))
    if provider == "local":
        base = (api_base or "http://localhost:11434").rstrip("/")
        url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return _openai_style(_get(url, headers), False)
    return []


def _problem(status: int | None) -> tuple[str, str]:
    if status in (401, 403):
        return "models_key_rejected", "The provider rejected your AI key, so the model list could not be loaded. Check the key in Settings."
    if status == 429:
        return "models_busy", "The provider is limiting requests right now. Wait a minute and press Refresh."
    return "models_unavailable", "Could not load the model list from the provider. Check the connection and press Refresh."


def list_models(provider: str, api_key: str | None, api_base: str | None, refresh: bool = False) -> tuple[list[ModelInfo], str]:
    """Return (models, source) where source is "live" or "cache"."""
    if provider != "openrouter" and provider != "local" and not api_key:
        raise HTTPException(status_code=400, detail={"code": "models_need_key", "message": "Add your AI key first. The model list is loaded with your key."})
    fingerprint = hashlib.sha256((api_key or "").encode()).hexdigest()[:16]
    cache_key = (provider, api_base or "", fingerprint)
    cached = _cache.get(cache_key)
    if cached and not refresh and time.monotonic() - cached[0] < _TTL_SECONDS:
        return cached[1], "cache"
    try:
        models = _request(provider, api_key, api_base)
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        # Class and status only: the provider's text is never logged or returned.
        logger.warning("model_list_failed provider=%s status=%s error_type=%s", provider, status, type(exc).__name__)
        code, message = _problem(status)
        raise HTTPException(status_code=502, detail={"code": code, "message": message})
    models.sort(key=lambda m: m.name.lower())
    _cache[cache_key] = (time.monotonic(), models)
    return models, "live"
