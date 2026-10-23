# API contract: warning groups, handoff, advisor, key setting (T5)

Status: contract only. Nothing here is implemented. Pydantic models are in `api/models_api.py` (section "Handoff / warning-group / advisor contract"). Backend tasks implement these paths and shapes. Frontend tasks T10 and T11 mock them in `web/src/api.js` until T20 to T22 switch to real calls.

## Conventions

- The handoff, steps and warning groups belong to an upload (`upload_id`). Replacing an upload creates a new upload with its own handoff, and the old one moves to history.
- Routers: warning groups, flag states, handoff, reupload choice and history go in a new `api/routers/handoff.py` (prefix `/upload` for upload-scoped paths, `/projects` for history). Advisor chat goes in `api/routers/ai.py` under `/ai/advisor`. Key setting goes in `api/routers/settings_router.py`.
- Auth "owner" means the existing project-access check used by `_require_upload_access` (project owner or admin). "Any user" means `get_current_user`. "Share token" means the mentor token used by `/share/{token}`.
- Error bodies use the existing envelope `{"error": {"code", "message", "field_errors", "request_id"}}`.
- Flag ids are the stable `id` strings added by T3 (rule + column, for example `missing_values:age`). Flags keep `severity` of `WARNING` or `ERROR`.
- Step shape: `{op, ...args, warning_ids: [flag_id], note}`. `op` is one of `recode, merge_values, retype, rename, fill, set, drop_rows, exclude_rows, note`. Arg names per op belong to `api/cleaning_steps.py` (T4); the contract treats extra keys as op args. A `note` op never changes data.

## Warning-group state model

- Group status: `open` (created, no message yet), `discussing` (at least one advisor turn, or a message after handling), `handled`.
- Acknowledge group: created already `handled`. ERROR flag ids are rejected.
- Clarify group: created `open`, becomes `discussing` on the first message, becomes `handled` on confirm. A confirm with zero steps is allowed and counts as handled with the note recorded.
- A new message in a `handled` clarify group (undo or revise) moves it back to `discussing`. Its flags show as `discussing` until the next confirm.
- A flag can be in at most one group that is not `handled`.
- Per-flag state returned to the data review screen: `unhandled`, `open`, `discussing`, `handled`, `resolved`. `resolved` applies only to ERROR flags and means the check no longer fires on the cleaned data. An ERROR in a handled clarify group whose check still fires stays `discussing` with the advisor message explaining why. Acknowledging never clears an ERROR.
- `unhandled_warning_count` counts WARNING flags in state `unhandled`, `open` or `discussing`. `unresolved_error_count` counts ERROR flags not `resolved`.

## Endpoints

| # | Method | Path | Request | Response | Auth | Errors |
|---|--------|------|---------|----------|------|--------|
| 1 | POST | `/upload/{upload_id}/warning-groups` | `WarningGroupCreate` | 201 `WarningGroupOut` | owner | 404 upload; 422 `unknown_flag_id`; 422 `error_flag_requires_clarify` (action acknowledge with an ERROR id); 409 `flag_already_grouped` |
| 2 | POST | `/upload/{upload_id}/warnings/acknowledge` | `WarningBatchAcknowledge` | 201 `WarningGroupOut` (one group, action acknowledge, status handled) | owner | same as 1 |
| 3 | GET | `/upload/{upload_id}/warning-groups` | none | `WarningGroupListOut` | owner | 404 |
| 4 | GET | `/upload/{upload_id}/flag-states` | none | `FlagStatesOut` | owner | 404 |
| 5 | GET | `/upload/{upload_id}/handoff` | none | `HandoffOut` (`read_only=false`) | owner | 404; 409 `handoff_pending_choice` is not an error, status is returned instead |
| 6 | GET | `/upload/{upload_id}/handoff/revisions` | none | `HandoffRevisionListOut` | owner | 404 |
| 7 | GET | `/share/{token}/handoff` | none | `HandoffOut` (`read_only=true`, current handoff and change log only) | share token | 404 invalid, revoked or expired token |
| 8 | GET | `/ai/advisor/groups/{group_id}` | none | `AdvisorThreadOut` | owner | 404 |
| 9 | POST | `/ai/advisor/groups/{group_id}/messages` | `AdvisorMessageIn` | `AdvisorReply` | owner | 404; 422 `not_clarify_group`; 429 rate limit; 503 `AdvisorUnavailableError` |
| 10 | POST | `/ai/advisor/groups/{group_id}/confirm` | `AdvisorConfirmIn` | `AdvisorConfirmOut` | owner | 404; 409 `stale_proposal` (proposal_id no longer current); 409 `no_pending_proposal`; 422 `step_rejected` (outside vocabulary or fails on the data) |
| 11 | POST | `/upload/{project_id}/replace/{upload_id}` (existing) | multipart as today | existing `UploadOut` fields plus `ReplaceUploadExtra` fields | project owner | as today |
| 12 | POST | `/upload/{upload_id}/reupload-choice` | `ReuploadFollowUpIn` | `ReuploadFollowUpOut` | owner | 404; 409 `no_choice_pending` |
| 13 | GET | `/projects/{project_id}/handoff-history` | none | `HandoffHistoryOut` | owner | 404 |
| 14 | DELETE | `/upload/{upload_id}/handoff` | none | `{"ok": true}` | owner | 404; 409 `handoff_is_current` (only a replaced handoff can be deleted) |
| 15 | PUT | `/settings/ai-key` | `AIKeyIn` | `AIKeyStatus` | any user (admin-only later) | 422 `key_invalid` |
| 16 | GET | `/settings/ai-key` | none | `AIKeyStatus` | any user | none |
| 17 | DELETE | `/settings/ai-key` | none | `AIKeyStatus` (falls back to env if set) | any user (admin-only later) | none |
| 18 | GET | `/ai/provider-status` | none | `ProviderStatusOut` | any user | none |
| 19 | GET | `/projects/{project_id}/resume` (existing) | none | existing `ProjectResumeOut` plus `gating: GatingOut` | owner | as today |

### Notes per area

Groups (1 to 4)
- Creation text is optional. For acknowledge it is stored as the note shown in the report. For clarify it is stored as the user's first suggestion and is sent to the advisor with the first message.
- Endpoint 2 is a convenience alias for endpoint 1 with `action="acknowledge"` and exists so the batch button has an obvious call. Backend may implement both with one function.
- Creating a clarify group does not call the AI. It works when the advisor is unavailable.
- Selected ids not in the upload's current flags return 422 `unknown_flag_id` with the offending ids in `field_errors.flag_ids`.

Handoff (5 to 7, 13, 14)
- `status`: `none` (not built yet), `pending_choice` (same-file re-upload awaiting keep or fresh), `current`, `replaced`, `deleted`.
- `change_log` is always returned. After deletion `markdown` is null and `steps` is empty, and the change log remains.
- Deleting a replaced handoff clears the markdown, steps and revision snapshots, and keeps the change log entries. There is no resident endpoint to delete a change log. Log removal is an admin task outside this contract (use `require_admin` if an endpoint is added later).
- The mentor endpoint returns the current handoff only, never history, and has no write counterpart.

Advisor chat (8 to 10)
- Every message is PHI-scrubbed server-side before the AI call, with `log_action` `phi_redacted` as elsewhere in `ai.py`.
- `warning_id` on a message ties the user's reply to one warning. Null means the whole group. The reply `proposals` has one entry per warning the advisor is proposing for, each with its own steps.
- Advisor goes first: the first POST to a new clarify group may send an empty-intent message such as "start" (or the user's optional creation text). The backend decides how to open; the contract only requires `message` to be non-empty.
- `needs_user_confirmation` is true when `proposals` contain steps awaiting agreement. The UI shows a read-back and a Confirm button that calls endpoint 10 with `proposal_id`. The UI never applies steps on its own.
- Confirm applies all steps of the current proposal, writes a handoff revision, sets the group `handled`, and returns recomputed flag states. `decline=true` drops the proposal and leaves the group `discussing`.
- Undo and revise use the same endpoints. The user asks in chat, the reply has `mode="undo"` or `mode="revise"` with the proposed steps (the full replacement step set for the affected warnings), and confirm applies it as a new revision.
- Requests outside the step vocabulary come back in `unapplied_notes`. They are not applied.

Unavailable advisor
- Applies to endpoints 9 and 10 and to `/ai/clarify`, `/ai/override-plan`, `/ai/interpret-results` once T7 lands.
- Status 503, body is `AdvisorUnavailableError`, `error.code = "advisor_unavailable"`. The frontend branches on `error.code`, not on the status alone.
- Acknowledge, group creation, flag states and handoff reads never depend on the advisor.

Re-upload (11, 12)
- Different file: response has `started_fresh: true`, `same_as_previous: false`, `choice_required: false`. A new handoff is already built and the old one is in history.
- Same file and same dictionary (both checksums equal): `same_as_previous: true`, `choice_required: true`. The new upload's handoff status is `pending_choice`. Gates treat it as fresh until a choice is made.
- `keep` copies steps, markdown and change log from the previous upload and continues the revision number (log entry kind `keep_from_previous`). `fresh` builds a new handoff from the new upload. Both return the resulting `HandoffOut`.

API key (15 to 18)
- The value is write-only. No response ever contains it. `last4` is null when `source` is `none`, and for `env` it is the last four characters of the env key.
- `source` is `settings` when a stored key exists (it overrides env), `env` when only the environment variable is set, otherwise `none`.
- `provider-status.advisor_available` is true when a key is configured or the stub provider is active. The no-key prompt uses it with `key_source`.
- The key is app-wide. The UI text says a saved key replaces it for everyone.

Gating (19)
- `ProjectResumeOut.gating` is a `GatingOut`. `current_screen` derivation uses `can_continue`. Backend `_has_unacknowledged_flags` and the analyze gate use the same computation as `can_continue` so the screen and the server agree.

## Tables and columns for T8 (one Alembic revision)

No second revision may add columns. Everything the contract needs is below. SQLite: add columns with `server_default` and use `batch_alter_table`.

`uploads` (new columns)

| column | type | default | purpose |
|--------|------|---------|---------|
| handoff_md | Text, nullable | null | handoff markdown, null when never built or deleted |
| handoff_steps | Text (JSON list), not null | `"[]"` | applied steps (`CleaningStep` list) |
| handoff_revision | Integer, not null | 0 | current revision number |
| handoff_revisions | Text (JSON list), not null | `"[]"` | revision history and change log. Entries: `revision, created_at, actor, kind, group_id, summary, rows_affected, steps_snapshot`. `steps_snapshot` (for undo) is dropped on document deletion, other keys stay |
| handoff_status | String(20), not null | `"none"` | `none, pending_choice, current, replaced, deleted` |
| handoff_updated_at | DateTime, nullable | null | last revision time |
| handoff_replaced_at | DateTime, nullable | null | set when the upload is replaced, the "replaced" flag for history |
| handoff_source_upload_id | Integer FK uploads.id, nullable, ON DELETE SET NULL | null | the previous upload when a `keep` is pending or taken |
| dictionary_checksum_sha256 | String(64), not null | `""` | with the existing `checksum_sha256`, source checksum for the same-file test |

The source upload checksum is the existing `uploads.checksum_sha256`. Same file means both `checksum_sha256` and `dictionary_checksum_sha256` match the replaced upload. Replaced state is also visible in the existing `uploads.status = "replaced"`; `handoff_replaced_at` keeps the date for the History tab.

`warning_groups` (new table)

| column | type | notes |
|--------|------|-------|
| id | Integer PK | |
| project_id | Integer FK projects.id ON DELETE CASCADE, indexed | |
| upload_id | Integer FK uploads.id ON DELETE CASCADE, indexed | |
| flag_ids | Text (JSON list of str), not null | stable flag ids |
| action | String(20), not null | `acknowledge` or `clarify` |
| text | Text, nullable | creation note or first suggestion |
| status | String(20), not null, default `open` | `open, discussing, handled` |
| advisor_turns | Text (JSON list), not null, default `"[]"` | `{role, text, warning_id, created_at}` |
| pending_proposal | Text (JSON), nullable | last unconfirmed `AdvisorReply` including `proposal_id` |
| created_by_user_id | Integer FK users.id ON DELETE SET NULL, nullable | |
| created_at | DateTime, not null | |
| updated_at | DateTime, not null | |
| handled_at | DateTime, nullable | |

Per-flag handled state is derived from `warning_groups` plus a re-run of the quality checks on the cleaned frame, so no table is needed for it. `pending_proposal` is the one column beyond the list in the task brief; it is needed so confirm can validate `proposal_id` and so a page reload keeps the proposal.

## Mock responses

### T11: data review

`GET /upload/42/flag-states`

```json
{
  "upload_id": 42,
  "flags": [
    {"flag_id": "missing_values:age", "severity": "WARNING", "state": "unhandled", "group_id": null, "action": null},
    {"flag_id": "duplicate_rows:*", "severity": "WARNING", "state": "handled", "group_id": 7, "action": "acknowledge"},
    {"flag_id": "category_variants:unit", "severity": "WARNING", "state": "discussing", "group_id": 8, "action": "clarify"},
    {"flag_id": "outcome_missing_30pct:readmit", "severity": "ERROR", "state": "open", "group_id": 9, "action": "clarify"}
  ],
  "unhandled_warning_count": 2,
  "unresolved_error_count": 1
}
```

`POST /upload/42/warnings/acknowledge` with `{"flag_ids": ["missing_values:age"], "text": "Missing at random, reviewed"}`

```json
{
  "id": 10, "project_id": 3, "upload_id": 42,
  "flag_ids": ["missing_values:age"], "action": "acknowledge",
  "text": "Missing at random, reviewed", "status": "handled", "turn_count": 0,
  "created_at": "2026-10-23T14:02:11", "updated_at": "2026-10-23T14:02:11",
  "handled_at": "2026-10-23T14:02:11"
}
```

`POST /upload/42/warning-groups` with `{"flag_ids": ["category_variants:unit"], "action": "clarify"}` returns the same shape with `"action": "clarify"`, `"status": "open"`, `"handled_at": null`.

422 for an ERROR in an acknowledge group:

```json
{"error": {"code": "error_flag_requires_clarify", "message": "ERROR flags can only be handled through Clarify.",
  "field_errors": {"flag_ids": ["outcome_missing_30pct:readmit"]}, "request_id": "9f2c1a"}}
```

`GET /projects/3/resume` addition:

```json
{"gating": {"unhandled_warning_count": 2, "unresolved_error_count": 1, "open_group_count": 2,
  "can_continue": false, "handoff_status": "current", "advisor_available": true}}
```

`POST /ai/advisor/groups/8/messages` with `{"message": "Merge mg and MG into mg", "warning_id": "category_variants:unit"}`

```json
{
  "advisor_available": true, "group_id": 8, "group_status": "discussing",
  "message": "I would merge the values 'mg' and 'MG' in unit into 'mg'. That changes 14 rows. Confirm?",
  "proposals": [{
    "warning_id": "category_variants:unit",
    "summary": "Merge 'MG' into 'mg' in column unit",
    "steps": [{"op": "merge_values", "column": "unit", "from": ["MG"], "to": "mg",
               "warning_ids": ["category_variants:unit"], "note": "User asked to merge case variants"}]
  }],
  "needs_user_confirmation": true, "proposal_id": "p_8_3", "mode": "propose", "unapplied_notes": []
}
```

`POST /ai/advisor/groups/8/confirm` with `{"proposal_id": "p_8_3"}`

```json
{
  "group_id": 8, "group_status": "handled", "applied": true, "handoff_revision": 4,
  "rows_affected": {"0": 14},
  "flag_states": {"upload_id": 42, "unhandled_warning_count": 1, "unresolved_error_count": 1,
    "flags": [{"flag_id": "category_variants:unit", "severity": "WARNING", "state": "handled", "group_id": 8, "action": "clarify"}]}
}
```

Advisor unavailable (HTTP 503):

```json
{"error": {"code": "advisor_unavailable", "message": "The QI Stat Advisor needs an AI key.", "field_errors": {}, "request_id": "a81f03"},
 "advisor_available": false, "reason": "no_key", "key_source": "none", "manual_path_available": true}
```

### T10: key setting and no-key prompt

`GET /ai/provider-status`

```json
{"advisor_available": false, "key_source": "none", "provider": null}
```

`GET /settings/ai-key` when unset, after `PUT /settings/ai-key` with `{"value": "sk-or-v1-abcdef123456"}`, and when only env is set:

```json
{"configured": false, "source": "none", "last4": null}
{"configured": true, "source": "settings", "last4": "3456"}
{"configured": true, "source": "env", "last4": "9z1q"}
```

`DELETE /settings/ai-key` when an env key exists returns `{"configured": true, "source": "env", "last4": "9z1q"}`; otherwise the unset shape.

`PUT` with a too-short value returns 422:

```json
{"error": {"code": "key_invalid", "message": "Enter the full key.", "field_errors": {"value": ["too short"]}, "request_id": "c4410e"}}
```

### T21 reference: history and re-upload

`GET /projects/3/handoff-history`

```json
{"project_id": 3, "items": [
  {"upload_id": 42, "file_name": "readmissions_q3.csv", "created_at": "2026-10-20T09:10:00", "replaced_at": "2026-10-22T16:40:00", "status": "replaced", "revision": 4, "change_log_entries": 4},
  {"upload_id": 40, "file_name": "readmissions_q2.csv", "created_at": "2026-10-10T11:00:00", "replaced_at": "2026-10-20T09:10:00", "status": "deleted", "revision": 2, "change_log_entries": 2}
]}
```

Replace response additions: different file `{"same_as_previous": false, "started_fresh": true, "choice_required": false}`; same file `{"same_as_previous": true, "started_fresh": false, "choice_required": true}`.

## Needs a decision

1. Advisor-unavailable status: this contract uses HTTP 503 with a structured body so existing fetch error paths still fire. If the frontend prefers HTTP 200 with `advisor_available: false`, the models support it with a one-line change. This is ours to settle unless the owner cares.
2. Editing a handled clarify group: a new message reopens it and its warnings count as unhandled until the next confirm. The owner may prefer that undo not block Continue until re-confirmed. This changes what a resident may do, so it is the clinical owner's call.
3. Same-file test uses file checksum and dictionary checksum together. If only the data file matches, it is treated as a different file (fresh).

## Amendments after implementation

The built behavior differs from the sections above in these places. The code is authoritative.

- AI key: `PUT /settings/ai-key` takes `{"key": "<8 to 512 chars>"}` (not `{value}`); `GET`/`PUT`/`DELETE` return `{configured, source: settings|env|none, last4, provider, advisor_available}`. Any signed-in user may call them for now (admin-only later). The key is app-wide.
- Handoff status values are `none, pending_choice, current, replaced, deleted`. The document is created as `current`.
- Revision `kind` is `created, apply, undo, revise, keep_from_previous`. The stored and displayed `actor` is only `user`, `advisor` or `system`; an email never appears in the document, the change log, or the mentor view.
- `GatingOut.pending_choice` (bool): `can_continue` is false while an identical-file re-upload awaits keep or fresh.
- `DELETE /upload/{upload_id}/warning-groups/{group_id}` cancels an unconfirmed clarify group and returns `FlagStatesOut`; 409 `group_not_cancellable` for a handled group, an acknowledge group, or a group that applied steps. Acknowledging flags that sit in an unconfirmed clarify group cancels that group first.
- Advisor replies: `ProposedSteps.dry_run` and `AdvisorReply.dry_run_error` are optional. A proposal records the handoff revision it was made against; confirming after the revision moved returns 409 `stale_proposal`. Any reply that is not a valid proposal clears the pending proposal. Confirm is claimed atomically, so a double confirm applies once.
- Flag states can include ERROR flags that appear only after cleaning (not in the stored `quality_flags`). An ERROR counts as resolved only when a re-check on the cleaned data no longer reports it and its column still exists.
- `/analyze/run` and `/analyze/run-plan` return 409 with plain-English text while warnings are unhandled, an ERROR remains, or a re-upload choice is pending. `/analyze/run` checks this after parameter validation.
- 429 from the rate limit arrives with `error.code == "HTTP_429"`.
- Mentor endpoint `GET /share/{token}/handoff` returns the current handoff read-only, with no steps and no email.
