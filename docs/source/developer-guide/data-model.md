# Data model

All 13 tables, as defined in `api/models_db.py` and enforced by the Alembic
migration chain below. SQLite enforces foreign keys at runtime (`PRAGMA
foreign_keys=ON`, set on every connection; see {doc}`architecture`), so the
`ondelete` behaviors listed here are real, not just documentation.

## Tables

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `email` | String(255) | unique, indexed |
| `password_hash` | Text | `pbkdf2_sha256$...` (see {doc}`security`) |
| `role` | String(50) | default `resident`; the first-ever registered user becomes `admin` |
| `created_at` | DateTime | default now |
| `disabled_at` | DateTime | nullable |

### `user_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | Integer FK → `users.id` | `ondelete=CASCADE` |
| `token_hash` | String(128) | unique, indexed; SHA-256 of the raw session token |
| `created_at` / `expires_at` / `last_seen_at` | DateTime | 8-hour session lifetime |
| `revoked_at` | DateTime | nullable |

### `projects`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `title`, `description` | String(255) / Text | |
| `status` | String(50) | default `draft`; also `archived` |
| `deadline` | String(20) | ISO date string, not a `Date` column — sourced from intake Q10 |
| `created_at` | DateTime | |
| `owner_user_id` | Integer FK → `users.id` | `ondelete=SET NULL` — an owner-deleted project survives, ownerless, as a legacy record |
| `archived_at` | DateTime | nullable |

### `uploads`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id` | Integer FK → `projects.id` | `ondelete=CASCADE` |
| `filename`, `original_filename`, `file_type`, `storage_key` | String | `storage_key` is the on-disk filename under `uploads_enc/` |
| `column_map`, `col_types`, `quality_flags` | Text (JSON) | defaults `{}`, `{}`, `[]` |
| `acknowledged_flags` | Text (JSON) | **nullable, no default** — `None` until the resident completes Data Review; distinguishing "no warnings acknowledged yet" from "acknowledged zero warnings" matters, see {doc}`security` |
| `size_bytes`, `checksum_sha256` | Integer / String(64) | integrity metadata for the encrypted file |
| `encrypted_path` | String(512) | filesystem path, outside the DB |
| `status` | String(20) | `active` \| `replaced` \| `deleted` |

### `intake_answers`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id` | Integer FK → `projects.id` | `ondelete=CASCADE` |
| `question_key` | String(10) | `q1`–`q10` |
| `answer` | Text | JSON-encoded when the answer is a dict/list, else the raw string |
| `is_unsure` | Boolean | true when the resident picked "I'm not sure" |

### `analysis_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id` | Integer FK → `projects.id` | `ondelete=CASCADE` |
| `upload_id` | Integer FK → `uploads.id` | `ondelete=CASCADE`, nullable (legacy runs predating this column) |
| `template` | String(50) | one of the six template ids |
| `parameters`, `result_json` | Text (JSON) | the exact request params and the template's full return dict |
| `code_r`, `code_spss`, `code_sas` | Text | generated code supplements (see {doc}`how-to`) |
| `created_at` | DateTime | |

### `audit_log`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id` | Integer FK → `projects.id` | `ondelete=CASCADE` |
| `action` | String(100) | e.g. `upload_created`, `share_created`, `intake_answers_saved` |
| `metadata_json` | Text (JSON) | passed through `sanitize_audit_metadata` before being written — see {doc}`security` |
| `timestamp` | DateTime | |

### `edit_history`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id` | Integer FK → `projects.id` | `ondelete=CASCADE` |
| `field` | String(100) | `title` \| `caption` \| `interpretation` |
| `original_text`, `edited_text` | Text | both kept — this *is* the report's Audit Trail / Resident Edits section |
| `timestamp` | DateTime | |

### `mentor_shares`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id` | Integer FK → `projects.id` | `ondelete=CASCADE` |
| `token` | String(128) | unique; `secrets.token_urlsafe(32)` |
| `mentor_email` | String(255) | nullable |
| `created_at`, `expires_at`, `revoked_at` | DateTime | shares default to a 30-day expiry |
| `regenerated_from_id` | Integer FK → `mentor_shares.id` | self-referential, `ondelete=SET NULL`; links a regenerated link back to the one it replaced |

`mentor_shares.comments_json` existed in an earlier schema revision and was
dropped in favor of the normalized `mentor_comments` table (migration
`c4e1f8a2d9b6`; see {doc}`decisions`).

### `mentor_comments`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `share_id` | Integer FK → `mentor_shares.id` | `ondelete=CASCADE`, not nullable |
| `project_id` | Integer FK → `projects.id` | `ondelete=CASCADE`, not nullable |
| `author_name` | String(255) | not nullable |
| `author_email` | String(255) | nullable; required only if the mentor wants to edit/delete their comment later |
| `text` | Text | not nullable |
| `created_at`, `updated_at`, `deleted_at` | DateTime | comments are soft-deleted (`deleted_at` set, row kept) |

### `ai_usage_events`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | Integer FK → `users.id` | `ondelete=SET NULL` |
| `project_id` | Integer FK → `projects.id` | `ondelete=SET NULL` |
| `model` | String(255) | not nullable |
| `prompt_chars`, `completion_chars` | Integer | character counts, never the actual prompt/completion text |
| `status` | String(50) | not nullable |
| `created_at` | DateTime | |

### `failure_log`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id`, `upload_id`, `run_id` | Integer FKs | all `ondelete=SET NULL` |
| `error_type`, `template`, `route`, `action`, `request_id` | String | |
| `message` | Text | a *safe* diagnostic message from a fixed lookup table, never a raw exception string (see {doc}`security`) |
| `safe_context_json` | Text (JSON) | sanitized request context |
| `timestamp` | DateTime | |

### `notification_deliveries`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `project_id`, `share_id` | Integer FKs | `ondelete=CASCADE`, nullable |
| `kind` | String(100) | e.g. `share_invite`, `deadline_reminder:{date}` |
| `recipient_email` | String(255) | not nullable |
| `status` | String(50) | `sent` \| `failed` \| `skipped` |
| `error_message` | Text | nullable; only ever a safe diagnostic string |
| `created_at`, `sent_at` | DateTime | |

### `app_settings`

| Column | Type | Notes |
|---|---|---|
| `key` | String(100) PK | must be listed in `settings_registry.REGISTRY` (see {doc}`how-to`) |
| `value` | Text | |

## Migration chain

Five revisions, applied in this order by `alembic upgrade head`:

| Revision | Down-revision | What it does |
|---|---|---|
| `cc61920dee93` | — | Placeholder initial migration (`upgrade`/`downgrade` both `pass`). |
| `5be9d78e473c` | `cc61920dee93` | Creates the first real tables: `projects`, `uploads`, `intake_answers`, `analysis_runs`, `audit_log`, `edit_history`, `mentor_shares`, `failure_log`, `app_settings`. |
| `9b3d2a7c4f10` | `5be9d78e473c` | The big one: adds `users`/`user_sessions` (auth), project ownership/archiving, upload metadata (`checksum_sha256`, `status`, etc.), `mentor_comments`, `ai_usage_events`, `notification_deliveries`, richer `failure_log` columns, and rebuilds every FK with explicit `ondelete` behavior via a named naming convention. |
| `c4e1f8a2d9b6` | `9b3d2a7c4f10` | Drops `mentor_shares.comments_json` now that `mentor_comments` is normalized. |
| `d4a1e6f0b8c2` | `c4e1f8a2d9b6` | Backfills any remaining nulls, then tightens columns that were backfilled-but-still-nullable in `9b3d2a7c4f10` (upload metadata, `analysis_runs.created_at`, `mentor_shares.created_at`) to `NOT NULL`, closing a gap between the ORM's contract and what a fresh `alembic upgrade head` actually produced. |

See {doc}`how-to` for how to add the next one, and {doc}`testing` for the
two tests (`test_migration_parity.py`, `test_migration_drift.py`) that keep
this chain honest against the ORM models.
