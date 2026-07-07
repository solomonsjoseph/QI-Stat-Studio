from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager

import api.models_db  # ensure all models are registered for tests and Alembic metadata
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.config import settings
from api.database import SessionLocal
from api.audit import safe_diagnostic_message
from api.models_db import FailureLog

class _RequestIdDefaultFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_RequestIdDefaultFilter())

logger = logging.getLogger(__name__)


def _parse_cors_origins(value: str) -> list[str]:
    text = (value or "").strip()
    if settings.environment == "production" and not os.environ.get("CORS_ORIGINS") and text == "http://localhost:5173":
        return []
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [] if settings.environment == "production" else ["http://localhost:5173"]
        return [item for item in parsed if isinstance(item, str)]
    return [item.strip() for item in text.split(",") if item.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "production" and settings.secret_key == "dev-secret-change-in-prod":
        raise RuntimeError("SECRET_KEY must be configured in production")
    yield


app = FastAPI(title="QI Stat Studio", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    if "application/json" in request.headers.get("content-type", ""):
        raw_body = await request.body()
        request.state.sanitized_body_ids = _ids_from_json_body(raw_body)

        async def receive():
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request._receive = receive
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response




def _int_path_param(request: Request, name: str) -> int | None:
    raw = request.path_params.get(name)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _merge_body_ids(ids: dict[str, int | None], body: dict | None) -> dict[str, int | None]:
    if not isinstance(body, dict):
        return ids
    for key in ids:
        if ids[key] is not None:
            continue
        raw = body.get(key)
        try:
            ids[key] = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            ids[key] = None
    return ids


def _ids_from_json_body(raw_body: bytes) -> dict[str, int | None]:
    ids: dict[str, int | None] = {"project_id": None, "upload_id": None, "run_id": None}
    try:
        parsed = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ids
    return _merge_body_ids(ids, parsed)


def _safe_route(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return str(template or request.url.path)


def _failure_context(request: Request, ids: dict[str, int | None]) -> dict:
    return {
        "method": request.method,
        "route": _safe_route(request),
        "project_id": ids.get("project_id"),
        "upload_id": ids.get("upload_id"),
        "run_id": ids.get("run_id"),
    }


async def _sanitized_request_ids(request: Request) -> dict[str, int | None]:
    ids = {
        "project_id": _int_path_param(request, "project_id"),
        "upload_id": _int_path_param(request, "upload_id"),
        "run_id": _int_path_param(request, "run_id"),
    }
    state_ids = getattr(request.state, "sanitized_body_ids", None)
    if isinstance(state_ids, dict):
        return _merge_body_ids(ids, state_ids)
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return ids
    try:
        body = await request.json()
    except Exception:
        return ids
    return _merge_body_ids(ids, body)


def _record_failure(request: Request, exc: Exception, request_id: str, ids: dict[str, int | None]) -> None:
    db = SessionLocal()
    try:
        row = FailureLog(
            project_id=ids.get("project_id"),
            upload_id=ids.get("upload_id"),
            run_id=ids.get("run_id"),
            error_type=type(exc).__name__,
            message=safe_diagnostic_message("internal_error"),
            route=_safe_route(request),
            action=request.method,
            request_id=request_id,
            safe_context_json=json.dumps(_failure_context(request, ids)),
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        logger.error("failed_to_record_failure", extra={"request_id": request_id})
    finally:
        db.close()


def _error_response(status_code: int, code: str, message: str, request_id: str, field_errors=None):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "field_errors": field_errors or {},
                "request_id": request_id,
            }
        },
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or "HTTP error")
        field_errors = detail.get("field_errors") if isinstance(detail.get("field_errors"), dict) else {}
        return _error_response(exc.status_code, f"HTTP_{exc.status_code}", message, request_id, field_errors)
    message = detail if isinstance(detail, str) else "HTTP error"
    return _error_response(exc.status_code, f"HTTP_{exc.status_code}", message, request_id)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    field_errors: dict[str, list[str]] = {}
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", []) if part not in ("body", "query", "path")]
        field = ".".join(loc) or "request"
        field_errors.setdefault(field, []).append(str(err.get("msg", "Invalid input")))
    return _error_response(422, "VALIDATION_ERROR", "Invalid request", request_id, field_errors)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    logger.error(
        "unhandled_exception route=%s method=%s error_type=%s",
        _safe_route(request),
        request.method,
        type(exc).__name__,
        extra={"request_id": request_id},
    )
    ids = await _sanitized_request_ids(request)
    _record_failure(request, exc, request_id, ids)
    return _error_response(500, "INTERNAL_ERROR", "Internal server error", request_id)


from api.routers import auth, projects, upload, analyze, ai, report, intake, share, settings_router, notifications, health  # noqa: E402,F401

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(ai.router)
app.include_router(report.router)
app.include_router(intake.router)
app.include_router(share.router)
app.include_router(settings_router.router)
app.include_router(notifications.router)

# Serve frontend static files when web/dist exists (production / Docker)
_dist = os.path.join(os.path.dirname(__file__), "..", "web", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
