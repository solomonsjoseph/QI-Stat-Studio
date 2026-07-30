# Architecture

## System overview

```{mermaid}
flowchart LR
    subgraph Browser
        UI["React SPA<br/>web/src"]
    end
    subgraph Server["FastAPI app (api/main.py)"]
        MW["Middleware chain<br/>CORS -> /api prefix strip -> request-id"]
        RT["11 routers<br/>auth, projects, upload, intake,<br/>analyze, ai, report, share,<br/>settings, notifications, health"]
        TPL["Statistical templates<br/>api/templates/*"]
        PHI["PHI scrubber<br/>api/middleware/phi_scrubber.py"]
    end
    DB[("SQLite via SQLAlchemy<br/>+ Alembic migrations")]
    ENC["/uploads_enc/<br/>Fernet-encrypted files/"]
    LLM[["LiteLLM -><br/>OpenRouter / OpenAI / local"]]

    UI -- "fetch('/api/...')" --> MW --> RT
    RT --> TPL
    RT <--> DB
    RT -- "encrypt/decrypt" --> ENC
    RT -- scrub before send --> PHI --> LLM
    UI -- "GET /mentor/:token (no auth)" --> RT
```

- **Frontend** (`web/src/`): a React 18 single-page app. `App.jsx` owns a
  single `AppCtx` context holding the whole wizard's state and a `screen`
  router driven by both in-memory state and the URL (`popstate`-aware, see
  `routeFromPath`/`applyResume`). Screens never talk to the backend directly
  except through `web/src/api.js`, a thin `fetch` wrapper that always sends
  `credentials: 'include'` and normalizes error responses into
  `{ message, code, requestId, fieldErrors }`.
- **Backend** (`api/`): a FastAPI app assembled in `api/main.py` from 11
  routers under `api/routers/`, each with its own URL prefix (`/auth`,
  `/projects`, `/upload`, `/intake`, `/analyze`, `/ai`, `/report`, `/share`,
  `/settings`, `/notifications`, plus unprefixed `/health` + `/readyz` +
  `/admin/failures`).
- **Database**: SQLite by default (`DB_URL`), reached through SQLAlchemy 2.0
  with a single global `SessionLocal` (`api/database.py`); `PRAGMA
  foreign_keys=ON` is set on every new SQLite connection via a `connect`
  event listener, since SQLite doesn't enforce FKs by default. Schema is
  owned entirely by Alembic (see {doc}`data-model`); the app never calls
  `Base.metadata.create_all()` outside tests.
- **Encrypted upload storage**: uploaded files are Fernet-encrypted and
  written to `uploads_enc/` on disk, referenced from the `uploads` table by
  `storage_key`/`encrypted_path`, never stored as blobs in the database.
- **AI provider**: reached only through `litellm.completion(...)`, which
  normalizes OpenRouter/OpenAI/local-Ollama-style calls behind one interface
  (see {doc}`how-to` for provider configuration).

## Request lifecycle

Every HTTP request passes through the same three-layer middleware stack,
outermost first:

1. **`CORSMiddleware`**: origins from `CORS_ORIGINS`, credentials allowed
   (required for the session cookie), all methods/headers allowed.
2. **`ApiPrefixMiddleware`**: strips a leading `/api` from the ASGI scope
   path before routing. This exists because the built frontend calls
   `/api/...` (matching the Vite dev proxy's mount point) in both dev and
   production, but the FastAPI routers themselves are registered without an
   `/api` prefix, so production serving needs exactly this rewrite to make
   the same frontend bundle work identically against the dev proxy and the
   real server.
3. **`request_id_middleware`**: assigns (or trusts an inbound)
   `X-Request-ID`, stores it on `request.state`, and echoes it back in the
   response header. For JSON bodies it also pre-parses `project_id` /
   `upload_id` / `run_id` into `request.state.sanitized_body_ids` *before*
   the route handler consumes the body stream. That's what lets the global
   exception handler attach identifying context to a failure log entry
   without re-reading (or logging) the full, possibly PHI-adjacent request
   body.

Three global exception handlers turn every error (`HTTPException`,
Pydantic's `RequestValidationError`, and any unhandled `Exception`) into the
same JSON envelope shape: `{"error": {"code", "message", "request_id",
"field_errors"}}`. Unhandled exceptions and `HTTPException`s both also write
a `FailureLog` row (`api/main.py:_record_failure`) with the sanitized
route/action/ids, so `GET /admin/failures` (see {doc}`api-reference`) has
something to show without ever persisting raw exception text or request
bodies that could contain PHI.

## Auth and sessions

There is no JWT and no third-party identity provider. Rutgers SSO is a
deferred v1 decision (see {doc}`decisions`). Instead:

- Passwords are hashed with PBKDF2-HMAC-SHA256, a random 16-byte salt per
  user, and 260,000 iterations, stored as
  `pbkdf2_sha256${iterations}${salt}${digest}` (`api/auth.py:hash_password`).
  Verification re-derives the digest with `hashlib.pbkdf2_hmac` and compares
  with `secrets.compare_digest` (constant-time).
- On login, a random 32-byte URL-safe token is minted
  (`secrets.token_urlsafe(32)`), its SHA-256 hash is stored in
  `user_sessions.token_hash` (never the raw token), and the raw token is
  signed (with `itsdangerous.URLSafeTimedSerializer` when available, or an
  HMAC-SHA256 fallback, `_fallback_signature`, when it isn't) before being
  set as the `qiss_session` cookie (`httponly`, `samesite=lax`, `secure`
  driven by `COOKIE_SECURE`). Sessions last 8 hours
  (`SESSION_SECONDS = 8 * 60 * 60`).
- Three FastAPI dependencies gate everything downstream:
  `get_current_user` (valid, non-revoked, non-expired session → the `User`
  row, else `401`), `require_admin` (adds a `role == "admin"` check, else
  `403`), and `require_project_owner` (loads the `Project`, allows admins or
  the owning user, else `403`/`404`). Every authenticated router depends on
  one of these three, so there's no separate authorization layer to keep in
  sync.
- Mentor share links (`/share/view/{token}` and friends) are the one
  deliberately unauthenticated surface. Access control there is entirely
  "do you have the unguessable token," checked per-request against
  `mentor_shares.revoked_at`/`expires_at` rather than any user session.

## The wizard as a state machine

The 10 screens (`SCREENS` in `web/src/App.jsx`) aren't just a linear
frontend flow: the backend independently derives "what screen should this
project be on" from what's actually persisted, in
`api/routers/projects.py:_derive_current_screen`. On `GET
/projects/{id}/resume`, that function walks: has a description → has all
required intake answers (Q2–Q6, Q9, Q10, plus Q7/Q8 unless Q3 is "No") → has
an active upload → has no unacknowledged data-quality flags → has an
analysis run → has an interpretation edit → else `download`. This
double-checking is deliberate: it means a resident can close the browser
mid-wizard, come back a week later on a different device, and land on
exactly the right screen without the frontend having to trust anything it
cached locally.

```{mermaid}
sequenceDiagram
    participant R as Resident (browser)
    participant FE as React SPA
    participant BE as FastAPI
    participant DB as SQLite

    R->>FE: Click "Resume"
    FE->>BE: GET /projects/{id}/resume
    BE->>DB: latest upload, run, share, intake answers
    DB-->>BE: rows
    BE->>BE: _derive_current_screen(...)
    BE-->>FE: ProjectResumeOut { ..., current_screen }
    FE->>FE: applyResume() hydrates AppCtx, routes to current_screen
    FE-->>R: renders the right screen, no re-entry needed
```
