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
| GET | `/projects` | Session | Lists the caller's own projects (admins see all); `limit` clamped 1-100, `offset >= 0`; excludes archived unless `status` is explicitly requested; sortable by `created_asc`/`title_asc`/`created_desc` (default). |
| GET | `/projects/{id}` | Owner | Single project. |
| GET | `/projects/{id}/resume` | Owner | Returns the project plus its latest active upload/run/non-revoked share plus a derived `current_screen` for "resume where you left off" (see {doc}`architecture`). |
| PATCH | `/projects/{id}` | Owner | Partial update; setting `status="archived"` stamps `archived_at`, moving away from `archived` clears it. |
| DELETE | `/projects/{id}` | Owner | `?purge=false` (default) archives; `?purge=true` deletes the row **and** the project's encrypted upload files from disk. |
| POST | `/projects/{id}/claim` | Admin | Assigns an owner to an ownerless ("legacy") project. This is how you fix a project whose original owner account is gone. |
| POST | `/projects/intake` | Session | Unified intake: multipart title, description, optional deadline, a dataset file and an optional data dictionary. The PHI gate runs on the data and dictionary first, then the project and upload are created in one request and `{project, upload}` is returned. |
| POST | `/projects/{id}/edits` | Owner | Records one `EditHistory` row for `title`/`caption`/`interpretation`; a `title` edit also updates `Project.title`. |

## `upload` (`/upload`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/upload/{project_id}` | Owner | Accepts `.csv`/`.xlsx`/`.xls` up to 50 MB; parses, validates shape (≥1 row, ≥1 column, no all-empty columns), auto-detects column types, runs data-quality checks, encrypts and stores the raw bytes, returns row count/column summary/quality flags/preview rows. |
| GET | `/upload/project/{id}` | Owner | Lists active uploads for a project. |
| GET | `/upload/{upload_id}` | Session | Upload metadata (ownership checked inside the handler, not via `require_project_owner`, since the URL only has an upload id). |
| DELETE | `/upload/{upload_id}` | Session | Soft-deletes (`status="deleted"`) and removes the encrypted file from disk. |
| POST | `/upload/{project_id}/replace/{upload_id}` | Owner | Marks the old upload `status="replaced"` and stores a new one in its place. The response adds `same_as_previous`, `started_fresh` and `choice_required`. A different file starts a new handoff and moves the old one to History. The same data file and dictionary leave the new upload in `pending_choice` until `POST /upload/{id}/reupload-choice`. |
| PUT | `/upload/{upload_id}/column-types` | Session | Saves confirmed/edited `col_types`, `column_map` and `column_roles`. |
| PATCH | `/upload/{upload_id}/acknowledged-flags` | Session | Saves the resident's acknowledged subset of quality flags (legacy path; the review screen now uses warning groups). The report Limitations section reads this field, not the raw `quality_flags` (see {doc}`security`). |
| POST | `/upload/{upload_id}/reupload-choice` | Session (upload access checked inside) | Body `{choice: "keep" | "fresh"}`. `keep` copies the earlier handoff steps, document and change log onto the new upload and replays them; `fresh` builds a new handoff. 409 `no_choice_pending` when nothing is waiting. Router: `api/routers/reupload.py`. |

## `warning-groups` (`/upload`)

Router: `api/routers/warning_groups.py`. A warning group ties one or more quality-flag ids to an action. Flag states are derived from the groups plus a re-check of the cleaned data.

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/upload/{id}/warning-groups` | Session (upload access) | Creates a group (`action` is `acknowledge` or `clarify`). 422 `unknown_flag_id`; 422 `error_flag_requires_clarify`; 409 `flag_already_grouped`. A clarify group makes no AI call. |
| POST | `/upload/{id}/warnings/acknowledge` | Session (upload access) | Batch acknowledge: one group, created already `handled`. |
| GET | `/upload/{id}/warning-groups` | Session (upload access) | Lists the groups. |
| DELETE | `/upload/{id}/warning-groups/{group_id}` | Session (upload access) | Cancels an unconfirmed clarify group and returns `FlagStatesOut`. 409 `group_not_cancellable` for a handled group, an acknowledge group, or one that applied steps. |
| GET | `/upload/{id}/flag-states` | Session (upload access) | Per-flag state (`unhandled`, `open`, `discussing`, `handled`, `resolved`), `unhandled_warning_count`, `unresolved_error_count` and `pending_choice`. The review screen enables Continue only when both counts are zero and `pending_choice` is false. |

## `advisor` (`/ai/advisor`)

Router: `api/routers/advisor.py`. The QI Stat Advisor chat for a clarify group. Every message is PHI-scrubbed server-side before the AI call.

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/ai/advisor/groups/{group_id}` | Session (access checked) | The saved thread for a group. |
| POST | `/ai/advisor/groups/{group_id}/messages` | Session (access checked) | Sends a user message and returns an `AdvisorReply` with optional step proposals, a `proposal_id` and `dry_run` row counts. Nothing is applied. 503 `advisor_unavailable` without a key; 429 on the rate limit. |
| POST | `/ai/advisor/groups/{group_id}/confirm` | Session (access checked) | Applies the pending proposal by `proposal_id` (or `decline`), writes a handoff revision, marks the group handled and returns recomputed flag states. 409 `stale_proposal` or `no_pending_proposal`; 422 `step_rejected`. Claimed atomically, so a double confirm applies once. |

## `handoff` (unprefixed)

Router: `api/routers/handoff.py`. The handoff document lists the agreed changes. Its structured steps are what the analysis paths replay on the raw file.

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/upload/{id}/handoff` | Session (upload access) | `HandoffOut`: markdown, steps, revision, `status` and change log. |
| GET | `/upload/{id}/handoff/revisions` | Session (upload access) | Revision list. |
| GET | `/share/{token}/handoff` | Public (token-gated) | Mentor view: current handoff and change log, read-only, no steps and no emails. |
| GET | `/projects/{id}/handoff-history` | Owner | Replaced and deleted handoffs for History. |
| DELETE | `/upload/{id}/handoff` | Session (upload access) | Deletes a replaced handoff document. The change log stays. 409 `handoff_is_current` or `handoff_not_replaced`. |
| DELETE | `/admin/upload/{id}/handoff-log` | Admin | Purges the change log of a deleted handoff. 409 `handoff_not_deleted` otherwise. |

## `analyze` (`/analyze`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/analyze/validate-plan/{project_id}` | Owner | Checks each plan item against the cleaned dataframe and returns per-item results plus the feasible templates. |
| POST | `/analyze/run` | Owner (via body's `project_id`) | Validates parameters against the template's schema (`extra="forbid"`) and the cleaned dataframe, then runs the template, generates R/SPSS/SAS code, persists an `AnalysisRun`, and returns the result. 409 with plain-English text while warnings are unhandled, an ERROR remains, or a re-upload choice is pending (checked after parameter validation). Failures are logged to `failure_log` with a safe diagnostic message. |
| POST | `/analyze/run-plan/{project_id}` | Owner | Runs every item of the confirmed analysis plan against the cleaned dataframe (raw upload plus agreed handoff steps) and returns `{runs, failures}`. Same 409 gate as `/analyze/run`. |

## `ai` (`/ai`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/ai/chat` | Owner (via body's `project_id`) | Scrubs **every string value in every message field** (not just `content`) before sending to the provider; enforces a per-request 4,000-character cap on user-role content; rate-limited per user/hour via the `ai_rate_limit_per_hour` setting; logs an `AIUsageEvent` with character counts only, never message text. |
| POST | `/ai/scrub-preview` | Session | Shows what PHI scrubbing would redact in a text, without an AI call. |
| POST | `/ai/clarify/{project_id}` | Owner | One turn of the project-design clarification conversation. |
| POST | `/ai/collection-guidance/{project_id}` | Owner | Data-collection guidance for the project. |
| POST | `/ai/recommend-plan/{project_id}` | Owner | Drafts the analysis plan with deterministic rules; the AI only writes explanations. |
| POST | `/ai/override-plan/{project_id}` | Owner | Applies a resident's change to the plan and re-validates it. |
| POST | `/ai/interpret-results/{project_id}` | Owner | Plain-language interpretation of the runs. Returns 503 `advisor_unavailable` without a key; the Results screen then shows the runs and a note. |

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
| PATCH | `/share/view/{token}/comment/{id}` | Public (token + matching `author_email` required) | Mentor edits their own comment. The email they originally commented with is the only proof of authorship. |
| DELETE | `/share/view/{token}/comment/{id}` | Public (token + matching `author_email` required) | Soft-deletes (`deleted_at`). |
| PATCH | `/share/{project_id}/comment/{id}` | Owner | Resident-side edit of any comment on their project. |
| DELETE | `/share/{project_id}/comment/{id}` | Owner | Resident-side delete of any comment on their project. |
| GET | `/share/view/{token}/report/{fmt}` | (none) | Always returns **HTTP 404** (`api/main.py`). Mentor report downloads were removed; this route answers old bookmarked or emailed links with a clean 404. |

## `settings` (`/settings`)

The AI key routes work for any signed-in user for now (admin-only later). The generic settings routes need an admin, so the Settings screen skips them for other users.

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/settings` | Admin | Lists all non-secret runtime settings from `settings_registry.REGISTRY`, falling back to each spec's default when unset. |
| PUT | `/settings` | Admin | Validates and upserts one setting; rejects keys in `REJECTED_DB_KEYS` (API keys, `secret_key`, `fernet_key`, `db_url`) with `400`. |
| GET | `/settings/ai-key` | Session | `{configured, source: settings|env|none, last4, provider, advisor_available}`. The key itself is never returned. |
| PUT | `/settings/ai-key` | Session | Body `{key}` (8 to 512 characters). Saves an app-wide key that overrides `.env`. Returns the same status shape. |
| DELETE | `/settings/ai-key` | Session | Removes the saved key; falls back to the `.env` key if one is set. |

## `notifications` (`/notifications`)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/notifications/deadline-reminders/run` | Admin | Finds active shares with a mentor email and a project deadline within the next 7 days, skips ones already reminded for that exact deadline, sends and records a delivery per share, returns `{sent, failed, skipped}`. Intended for a periodic runner (e.g. cron). There is no built-in scheduler. |

## `health` / admin ops (unprefixed)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/health` | Public | `{"status": "ok"}`. No DB touch; a pure liveness probe. |
| GET | `/readyz` | Public | Checks `SELECT 1` against the DB and that `settings.fernet` builds successfully; `200 {"status": "ready"}` when both pass, else `503` with a per-check breakdown. |
| GET | `/admin/failures` | Admin | Paginated, filterable (`project_id`, `request_id`) view over `failure_log`, for triaging what went wrong without ever exposing raw exception text or request bodies. |
