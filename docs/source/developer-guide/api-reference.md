# API reference

All routes are also live in Swagger UI at `/docs` while the backend is
running. This page adds the auth requirement and behavioral detail Swagger's
auto-generated schema doesn't capture on its own.

Three auth dependencies gate everything below (see {doc}`architecture` for
exactly what each checks):

- **Session** = `get_current_user` (any signed-in user).
- **Admin** = `require_admin` (signed-in **and** `role == "admin"`).
- **Owner** = `require_project_owner` (signed-in, and either admin or the
  project's `owner_user_id`).
- **Public** = no auth dependency at all (health checks and mentor share
  views).

## `auth` (`/auth`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/auth/register` | Public | Creates a user; the **first user ever registered** gets `role="admin"`, every later registration gets `role="resident"`. Sets the session cookie on success. |
| POST | `/auth/login` | Public | Verifies password (PBKDF2, constant-time compare), creates a new session, sets the session cookie. |
| POST | `/auth/logout` | Session | Revokes the current session server-side and clears the cookie. |
| GET | `/auth/me` | Session | Returns the current user. |

## `projects` (`/projects`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/projects` | Session | Creates a project owned by the caller, `status="draft"`. |
| GET | `/projects` | Session | Lists the caller's own projects (admins see all); `limit` clamped 1–100, `offset ≥ 0`; excludes archived unless `status` is explicitly requested; sortable by `created_asc`/`title_asc`/`created_desc` (default). |
| GET | `/projects/{id}` | Owner | Single project. |
| GET | `/projects/{id}/resume` | Owner | Returns the project plus its latest active upload/run/non-revoked share plus a derived `current_screen` — this is what powers "resume where you left off" (see {doc}`architecture`). |
| PATCH | `/projects/{id}` | Owner | Partial update; setting `status="archived"` stamps `archived_at`, moving away from `archived` clears it. |
| DELETE | `/projects/{id}` | Owner | `?purge=false` (default) archives; `?purge=true` deletes the row **and** the project's encrypted upload files from disk. |
| POST | `/projects/{id}/claim` | Admin | Assigns an owner to an ownerless ("legacy") project — the only way to fix a project whose original owner account is gone. |
| POST | `/projects/{id}/edits` | Owner | Records one `EditHistory` row for `title`/`caption`/`interpretation`; a `title` edit also updates `Project.title`. |

## `intake` (`/intake`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/intake/{project_id}` | Owner | Upserts intake answers. If Q10 includes a mentor email, this call **also creates or reuses a mentor share** through the same code path as `POST /share/{project_id}/create` (deduplicated by email — saving the same Q10 twice never creates two shares). Q10's `deadline` is stored on `Project.deadline`. Writes an `intake_answers_saved` audit log entry with the saved question keys (never the answer values). |
| GET | `/intake/{project_id}` | Owner | Returns saved answers plus a derived `intervention_date` parsed from Q7. |

## `upload` (`/upload`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/upload/{project_id}` | Owner | Accepts `.csv`/`.xlsx`/`.xls` up to 50 MB; parses, validates shape (≥1 row, ≥1 column, no all-empty columns), auto-detects column types, runs data-quality checks, encrypts and stores the raw bytes, returns row count/column summary/quality flags/preview rows. |
| GET | `/upload/project/{id}` | Owner | Lists active uploads for a project. |
| GET | `/upload/{upload_id}` | Session | Upload metadata (ownership checked inside the handler, not via `require_project_owner`, since the URL only has an upload id). |
| DELETE | `/upload/{upload_id}` | Session | Soft-deletes (`status="deleted"`) and removes the encrypted file from disk. |
| POST | `/upload/{project_id}/replace/{upload_id}` | Owner | Marks the old upload `status="replaced"` and stores a new one in its place. |
| PUT | `/upload/{upload_id}/column-types` | Session | Saves confirmed/edited `col_types` and `column_map`. |
| PATCH | `/upload/{upload_id}/acknowledged-flags` | Session | Saves the resident's acknowledged subset of quality flags — this is what the report's Limitations section reads from, not the raw `quality_flags` (see {doc}`security`). |

## `analyze` (`/analyze`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/analyze/{project_id}/recommend` | Owner | Runs `select_template` against saved intake answers, returns 3 ranked `{template, description, recommended}` entries. |
| POST | `/analyze/run` | Owner (via body's `project_id`) | Validates parameters against the template's schema (`extra="forbid"`) and against the actual uploaded dataframe's columns/shape, then runs the template, generates R/SPSS/SAS code, persists an `AnalysisRun`, and returns the result. Failures are logged to `failure_log` with a safe diagnostic message. |

## `ai` (`/ai`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/ai/intake-prefill` | Owner (via body's `project_id`) | Scrubs the project description, asks the AI provider to draft Q2–Q7 answers, returns them plus whether/how much redaction happened. |
| POST | `/ai/chat` | Owner (via body's `project_id`) | Scrubs **every string value in every message field** (not just `content`) before sending to the provider; enforces a per-request 4,000-character cap on user-role content; rate-limited per user/hour via the `ai_rate_limit_per_hour` setting; logs an `AIUsageEvent` with character counts only, never message text. |

## `report` (`/report`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/report/{run_id}/docx` | Session (project access checked inside) | Streams a generated Word document: methods, results table/figure, interpretation, Limitations (acknowledged flags only), code supplement(s), mentor comments, and a two-part Audit Trail (run metadata table + full project `audit_log` + resident edit original/edited text). |
| GET | `/report/{run_id}/pdf` | Session (project access checked inside) | Same content as the DOCX, rendered with ReportLab instead of python-docx. |

## `share` (`/share`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/share/{project_id}/create` | Owner | Creates a share (30-day default expiry) or returns an existing active one for the same `mentor_email`; emails an invite when an email is given and reports `notification_status` (`sent`/`failed`/`not_requested`/`existing_share`) without ever blocking share creation on email delivery. |
| POST | `/share/{project_id}/revoke` | Owner | Requires an explicit `token` or `mentor_email` target; sets `revoked_at`. |
| POST | `/share/{project_id}/regenerate` | Owner | Revokes the matched share and issues a new one, linked via `regenerated_from_id`. |
| GET | `/share/view/{token}` | Public | The mentor's read-only view: report content plus comments. No download link is present anywhere in this response. |
| POST | `/share/view/{token}/comment` | Public (token-gated) | Mentor adds a comment; no account needed. |
| PATCH | `/share/view/{token}/comment/{id}` | Public (token + matching `author_email` required) | Mentor edits their own comment — the email they originally commented with is the only proof of authorship. |
| DELETE | `/share/view/{token}/comment/{id}` | Public (token + matching `author_email` required) | Soft-deletes (`deleted_at`). |
| PATCH | `/share/{project_id}/comment/{id}` | Owner | Resident-side edit of any comment on their project. |
| DELETE | `/share/{project_id}/comment/{id}` | Owner | Resident-side delete of any comment on their project. |
| GET | `/share/view/{token}/report/{fmt}` | — | Explicitly wired to always return **HTTP 404** (`api/main.py`) — mentor report downloads were a considered and removed feature; this route exists purely to answer old bookmarked/emailed links with a clean 404 instead of a routing error. |

## `settings` (`/settings`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/settings` | Admin | Lists all non-secret runtime settings from `settings_registry.REGISTRY`, falling back to each spec's default when unset. |
| PUT | `/settings` | Admin | Validates and upserts one setting; rejects keys in `REJECTED_DB_KEYS` (API keys, `secret_key`, `fernet_key`, `db_url`) with `400`. |

## `notifications` (`/notifications`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/notifications/deadline-reminders/run` | Admin | Finds active shares with a mentor email and a project deadline within the next 7 days, skips ones already reminded for that exact deadline, sends and records a delivery per share, returns `{sent, failed, skipped}`. Intended to be run periodically (e.g. cron) — there is no built-in scheduler. |

## `health` / admin ops — unprefixed

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/health` | Public | `{"status": "ok"}`. No DB touch — a pure liveness probe. |
| GET | `/readyz` | Public | Checks `SELECT 1` against the DB and that `settings.fernet` builds successfully; `200 {"status": "ready"}` when both pass, else `503` with a per-check breakdown. |
| GET | `/admin/failures` | Admin | Paginated, filterable (`project_id`, `request_id`) view over `failure_log`, for triaging what went wrong without ever exposing raw exception text or request bodies. |
