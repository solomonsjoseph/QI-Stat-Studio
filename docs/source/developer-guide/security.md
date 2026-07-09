# Security and PHI handling

This app handles clinical QI data, so three protections apply throughout the
codebase, independently of each other: encryption at rest, PHI scrubbing
before any AI call, and sanitized logging. Auth/session mechanics are
covered in {doc}`architecture`; this page covers the rest.

## Encryption at rest

Every uploaded file is encrypted with `cryptography.fernet.Fernet` the
moment it's received (`settings.fernet.encrypt(raw)` in
`api/routers/upload.py`) and written to `uploads_enc/`, referenced from the
`uploads` table only by path — the database never holds file bytes.
`FERNET_KEY` is required at startup; `Settings.fernet` (`api/config.py`)
raises `RuntimeError` the first time it's accessed if the key is missing, so
there is no accidental "run without encryption" mode.

## PHI scrubbing before every AI call

`api/middleware/phi_scrubber.py`'s `scrub_text(text)` runs on **every**
string sent toward an LLM provider — the project description
(`/ai/intake-prefill`) and every string field of every chat message
(`/ai/chat`, scrubbed field by field, not just the `content` key). It
combines:

- Regex patterns for MRNs (`MRN[:\s#]*\d{5,10}`), SSNs, phone numbers,
  emails, `DOB:` lines, standalone `MM/DD/YYYY` and `YYYY-MM-DD` dates, and
  street addresses.
- spaCy's `en_core_web_sm` NER model (when installed — see
  {doc}`getting-started`) for `PERSON`, `DATE`, and `ORG` entities the
  regexes would miss.

Every match, from either method, is replaced with the literal string
`[REDACTED]`, and a redaction count is returned alongside the cleaned text.
`/ai/chat` sums that count across every scrubbed field and reports
`phi_redacted`/`redaction_count` back to the frontend, which shows a banner
so the resident knows de-identification actually happened — it's never a
silent substitution.

:::{caution}
The docstring on `scrub_text` says it plainly: this is **defense-in-depth
for accidental disclosure, not a guarantee that arbitrary clinical text is
PHI-free**. Treat it as a safety net, not a reason to relax what gets typed
into free-text fields in the first place.
:::

Independently of scrubbing, full spreadsheet rows are architecturally never
in the AI request path at all — `/ai/chat` and `/ai/intake-prefill` only
ever see the project description, chat messages, and small pre-computed
result summaries (`result_summary`, template name), never the uploaded
dataframe. There's no code path that could leak raw CSV rows to a provider
even if scrubbing were disabled.

## Sanitized audit and failure logs

Two independent sanitizers make sure logs and audit trails stay safe to
read (and to store) without engineers having to remember to redact anything
by hand at each call site:

- **`sanitize_audit_metadata`** (`api/audit.py`), used by every
  `log_action(...)` call that writes to `audit_log`: recursively strips any
  dict key whose lowercased name *contains* one of a fixed blocked-substring
  list — `password`, `secret`, `token`, `api_key`, `raw`, `prompt`,
  `content`, `email`, `name`, `text`, `url`, `title`, `description`,
  `deadline` — and records which fields were dropped under a `fields` key
  instead of silently vanishing. This is why, for example, `upload_created`
  audit entries record `upload_id`/`file_type`/`size_bytes` but never a
  filename, and `intake_answers_saved` records only the **question keys**
  that were saved, never the answer text.
- **`safe_diagnostic_message`** (`api/audit.py`), used by the global
  exception handler and `failure_log` writes: maps an error *kind* (
  `internal_error`, `analysis_failed`, `notification_failed`,
  `ai_service_unavailable`) to one fixed, pre-approved sentence. Raw
  exception messages and stack traces are never written to `failure_log` or
  returned to the client — only the request id, route, action, and this
  fixed sentence, which is enough for `GET /admin/failures` to be useful for
  triage without becoming a second place PHI could leak into.

## The mentor-share trust boundary

`/share/view/{token}` and its comment endpoints are the app's only
intentionally unauthenticated surface. Their security model is entirely
capability-based: possessing the 32-byte URL-safe token
(`secrets.token_urlsafe(32)`, effectively unguessable) is both necessary and
sufficient to view the report and comment. There is deliberately no download
capability on this path at all — not even for an authenticated mentor —
enforced at two layers: the mentor-view response never includes a
`figure`/report *file*, only inline JSON content, and the legacy download
route `/share/view/{token}/report/{fmt}` is hard-wired to return `404`
regardless of what's requested (see {doc}`api-reference`). Revoking a share
(`mentor_shares.revoked_at`) takes effect immediately — `_active_share_or_404`
checks it on every request, so there's no caching or grace period to work
around.

## Reporting a security concern

There is no bundled vulnerability-disclosure process in this repository —
route concerns to the maintainers directly rather than filing a public
issue, particularly for anything touching PHI handling or auth.
