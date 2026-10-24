# Security and PHI handling

This app handles clinical QI data, so three protections apply throughout the
codebase, independently of each other: encryption at rest, PHI scrubbing
before any AI call, and sanitized logging. Auth/session mechanics are
covered in {doc}`architecture`; this page covers the rest.

## Encryption at rest

Every uploaded file is encrypted with `cryptography.fernet.Fernet` the
moment it's received (`settings.fernet.encrypt(raw)` in
`api/routers/upload.py`) and written to `uploads_enc/`, referenced from the
`uploads` table only by path. The database never holds file bytes.
`FERNET_KEY` is required at startup; `Settings.fernet` (`api/config.py`)
raises `RuntimeError` the first time it's accessed if the key is missing, so
there is no accidental "run without encryption" mode.

## PHI scrubbing before every AI call

`api/middleware/phi_scrubber.py`'s `scrub_text(text)` runs on **every**
string sent toward an LLM provider: the project description
(`/ai/clarify`) and every string field of every chat message
(`/ai/chat`, scrubbed field by field, not just the `content` key). It
combines:

- Regex patterns for MRNs (`MRN[:\s#]*\d{5,10}`), SSNs, phone numbers,
  emails, `DOB:` lines, standalone `MM/DD/YYYY` and `YYYY-MM-DD` dates, and
  street addresses.
- spaCy's `en_core_web_sm` NER model (when installed, see
  {doc}`getting-started`) for `PERSON`, `DATE`, and `ORG` entities the
  regexes would miss. The small model also tags project vocabulary, so
  `_ner_redactable` in `api/middleware/phi_scrubber.py` keeps what is not an
  identifier: a single token with a digit (SGLT2, GLP-1), payer names
  (Medicaid, Medicare), and dates that do not reach a specific day ("January
  2025", "3 months"). Multi-word names with a digit, such as "Maria Garcia 2B",
  are still redacted. The dataset profile's dictionary definitions are scrubbed
  when the profile is built, because the profile goes to the AI.

Every match, from either method, is replaced with the literal string
`[REDACTED]`, and a redaction count is returned alongside the cleaned text.
`/ai/chat` sums that count across every scrubbed field and reports
`phi_redacted`/`redaction_count` back to the frontend, which shows a banner
so the resident knows de-identification actually happened. It's never a
silent substitution.

:::{caution}
The docstring on `scrub_text` says it plainly: this is **defense-in-depth
for accidental disclosure, not a guarantee that arbitrary clinical text is
PHI-free**. Treat it as a safety net, not a reason to relax what gets typed
into free-text fields in the first place.
:::

Independently of scrubbing, full spreadsheet rows are architecturally never
in the AI request path at all. `/ai/chat`, `/ai/clarify` and the advisor chat only ever
see the project description, chat messages, and small pre-computed result
summaries (`result_summary`, template name), never the uploaded dataframe.
There's no code path that could leak raw CSV rows to a provider even if
scrubbing were disabled.

## Sanitized audit and failure logs

Two independent sanitizers keep logs and audit trails safe to read (and to
store), so engineers don't have to remember to redact anything by hand at
each call site:

- **`sanitize_audit_metadata`** (`api/audit.py`), used by every
  `log_action(...)` call that writes to `audit_log`: recursively strips any
  dict key whose lowercased name *contains* one of a fixed blocked-substring
  list (`password`, `secret`, `token`, `api_key`, `raw`, `prompt`,
  `content`, `email`, `name`, `text`, `url`, `title`, `description`,
  `deadline`), and records which fields were dropped under a `fields` key
  instead of silently vanishing. That's why, for example, `upload_created`
  audit entries record `upload_id`/`file_type`/`size_bytes` but never a
  filename, and `intake_answers_saved` records only the **question keys**
  that were saved, never the answer text.
- **`safe_diagnostic_message`** (`api/audit.py`), used by the global
  exception handler and `failure_log` writes: maps an error *kind*
  (`internal_error`, `analysis_failed`, `notification_failed`,
  `ai_service_unavailable`) to one fixed, pre-approved sentence. Raw
  exception messages and stack traces are never written to `failure_log` or
  returned to the client, only the request id, route, action, and this
  fixed sentence. That's enough for `GET /admin/failures` to be useful for
  triage without becoming a second place PHI could leak into.
- **`advisor_failed`** (`api/ai_key.py`): when a provider call raises, the
  response is picked from the exception *class* only. Rate limits, timeouts and
  connection errors give `503 advisor_busy` ("busy right now, wait a minute");
  anything else gives `502 advisor_error`. Both sentences tell the resident they
  can continue without the QI Stat Advisor. The provider's own text can echo
  request content and is never returned.

## Sign-in, passwords and uploads (OWASP)

These follow the OWASP Password Storage, Authentication and File Upload cheat sheets.

- **Passwords:** PBKDF2-HMAC-SHA256, 600,000 iterations (`PASSWORD_ITERATIONS`). Older
  hashes still verify and are upgraded at the next sign-in. Argon2id is the other
  OWASP-recommended choice; PBKDF2 needs no extra dependency.
- **Brute force:** `api/throttle.py` counts failed sign-ins per account identifier, 5 failures in
  15 minutes lock it for 15 minutes (HTTP 429 with `Retry-After`). Unknown emails are counted
  the same way, so a lockout does not reveal which accounts exist. A per-IP limit covers
  attempts spread across accounts (60 per 15 minutes) and bulk registration (10 per hour).
  Failures and lockouts go to the audit log, with a short hash of the email, never the address.
  A dummy password check runs for unknown emails so response time does not reveal them.
- **Limitations:** the counters live in process memory. They reset on restart and are not
  shared between workers, which is fine for a git-clone install or one worker; use the database
  or Redis before running several. Registration still answers "Email already registered",
  because the app sends no confirmation email. There is no multi-factor sign-in and no
  breached-password check. The per-IP limit sees the proxy's address behind a reverse proxy.
- **Per-user AI keys:** a saved key is a Fernet-encrypted row per user. Another account never
  uses it, and the status endpoint returns only the last four characters.
- **Mentor comments:** public share views show no author email. Editing or deleting a comment
  needs a secret returned once to the person who posted it and kept in that browser. The
  project owner can still edit and delete comments from their own view.
- **Uploads:** read in chunks and stopped at 50 MB (10 MB for a dictionary). xlsx and docx are
  zip files, so their expanded size is capped at 250 MB and any entry that expands more than
  100 times is refused. Datasets are capped at 200,000 rows and 500 columns, dictionaries at 200
  PDF pages and 500,000 characters.

## The mentor-share trust boundary

`/share/view/{token}` and its comment endpoints are the app's only
intentionally unauthenticated surface. Their security model is entirely
capability-based: possessing the 32-byte URL-safe token
(`secrets.token_urlsafe(32)`, effectively unguessable) is both necessary and
sufficient to view the report and comment. There is deliberately no
download capability on this path at all, not even for an authenticated
mentor, and that's enforced at two layers: the mentor-view response never
includes a `figure`/report *file*, only inline JSON content, and the legacy
download route `/share/view/{token}/report/{fmt}` is hard-wired to return
`404` regardless of what's requested (see {doc}`api-reference`). Revoking a
share (`mentor_shares.revoked_at`) takes effect immediately;
`_active_share_or_404` checks it on every request, so there's no caching or
grace period to work around.

## Reporting a security concern

There is no bundled vulnerability-disclosure process in this repository.
Route concerns to the maintainers directly rather than filing a public
issue, particularly for anything touching PHI handling or auth.
