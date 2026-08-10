# How-to guides

## Configure the AI provider

The app talks to whichever LLM provider you configure through
[LiteLLM](https://github.com/BerriAI/litellm), which normalizes the
OpenRouter/OpenAI/Ollama-style APIs behind one call. Set `AI_PROVIDER` to
one of `openrouter` (default), `openai`, or `local`, then fill in the
matching credentials:

| `AI_PROVIDER` | Required | Optional |
|---|---|---|
| `openrouter` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` (default `anthropic/claude-sonnet-4-6`) |
| `openai` | `OPENAI_API_KEY` | `OPENAI_MODEL` (default `gpt-4o-mini`) |
| `local` (e.g. Ollama) | — | `LOCAL_API_BASE` (default `http://localhost:11434`), `LOCAL_API_KEY`, `LOCAL_MODEL` (default `llama3.1`) |

Without valid provider credentials, AI endpoints (`/ai/intake-prefill`,
`/ai/chat`) return an "unavailable" response. Core upload/analysis/report
functionality doesn't depend on the AI provider and keeps working either
way. `ai_provider` and the per-provider model names are also editable at
runtime by an admin from **Settings** (backed by `api/settings_registry.py`)
without restarting the server. API keys are not: they're boot-time-only and
never exposed through that screen (see {doc}`security`).

## Add a new statistical template

A template isn't just one function; it's eight coordinated pieces. Use the
six existing templates in `api/templates/` as your model:

1. **The runner** (`api/templates/your_template.py`): a function
   `run_your_template(df, params)` returning a dict with (at minimum) `table`,
   `figure_base64`, `methods`, `result_summary`, and `interpretation` keys —
   every template must include `interpretation`
   (`tests/test_interpretation.py` enforces this contract across all six).
2. **Register it**: add `"your_template": run_your_template` to
   `TEMPLATE_REGISTRY` in `api/templates/registry.py`.
3. **Parameter schema** (`api/analysis_schemas.py`): a
   `YourTemplateParams(AnalysisParamsBase)` Pydantic model (inherits
   `extra="forbid"`), and an entry in `_TEMPLATE_COLUMN_FIELDS` listing which
   fields are dataset columns that must be validated against the uploaded
   file's actual columns.
4. **Data validation** (`api/analysis_validation.py`): add a branch in
   `validate_analysis_inputs` for your template id, using the shared
   `_date_parse_errors` / `_numeric_parse_errors` /
   `_time_series_points` helpers as appropriate, and pick a minimum-data-size
   threshold that produces a clear error rather than a confusing statistical
   failure.
5. **Code generation** (`api/templates/codegen.py`): add a branch to each of
   `generate_r_code`, `generate_spss_code`, and `generate_sas_code`.
   Templates you haven't implemented yet return the exact fallback string
   `# {language} code for template "{template}" not yet implemented.`. Don't
   ship a template whose Q9 export is still that placeholder.
6. **Selection logic** (`api/routers/analyze.py`): decide where your new
   template fits into `select_template`'s branch order, and add a
   one-sentence entry to `_DESCRIPTIONS`.
7. **Frontend** (`web/src/screens/AnalysisSelection.jsx`): add a matching
   `{ template, label, description }` entry to the local `TEMPLATES` array so
   it renders even before/if the backend recommendation call resolves.
8. **Parameter mapping** (`web/src/screens/ParameterSelection.jsx`): add your
   template's required fields to the field-requirements map so the mapping
   screen renders the right dropdowns.

Then write tests mirroring `tests/test_time_series_templates.py` (runner
behavior), `tests/test_template_selection.py` (selection branch), and
`tests/test_codegen.py` (R/SPSS/SAS non-placeholder output) for your new
template.

## Write a database migration

```bash
alembic revision -m "short description"
```

Edit the generated file's `upgrade()`/`downgrade()`. SQLite can't
`ALTER TABLE` arbitrarily, so for compatibility use
`op.batch_alter_table(...)`; every migration in this repo already does,
e.g. `alembic/versions/d4a1e6f0b8c2_tighten_backfilled_not_null_columns.py`,
which also shows the pattern for backfilling data before tightening a
column to `NOT NULL`. See {doc}`data-model` for the full existing migration
chain.

Before committing, confirm your migration produces a schema that actually
matches the SQLAlchemy models. This repo has two dedicated regression tests
for exactly that gap:

```bash
FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q tests/test_migration_parity.py tests/test_migration_drift.py
```

`test_migration_parity.py` diffs `alembic upgrade head` against
`Base.metadata.create_all()` column-for-column; `test_migration_drift.py`
pins specific schema details (token lengths, FK behavior, nullability) that
have broken before.

## Add a runtime-editable setting

Add an entry to `REGISTRY` in `api/settings_registry.py`:

```python
"my_setting": SettingSpec("my_setting", "string", secret=False, runtime=True, default=lambda: "some default"),
```

If the value should never be admin-editable (an API key, the database URL,
the Fernet key), add its key to `REJECTED_DB_KEYS` instead, or simply don't
register it at all, since `require_allowed_setting` rejects anything not in
`REGISTRY`. Runtime settings are readable via `GET /settings` and writable
via `PUT /settings` (admin-only both ways); see {doc}`api-reference`.

## Run the app in Docker

```bash
docker build -t qi-stat-studio .
docker run -p 8000:8000 \
  -e FERNET_KEY=<your-fernet-key> \
  -e SECRET_KEY=<production-session-secret> \
  -e AI_PROVIDER=openrouter \
  -e OPENROUTER_API_KEY=<optional-openrouter-key> \
  qi-stat-studio
```

The image is a two-stage build: `node:20-slim` builds `web/dist`, then
`python:3.11-slim` installs `requirements.txt` plus the spaCy model and
copies the built frontend in alongside the backend. The container's entry
point is `alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port
8000`, so migrations run automatically on every container start and a fresh
container against a blank volume produces a fully migrated schema with no
manual step. Both the API and the built frontend are served from the same
`http://localhost:8000` in this mode. `api/main.py` mounts `web/dist` as
static files when that directory exists, which only happens in the
Docker/production build; in local dev, Vite serves the frontend itself.

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `FERNET_KEY` | **Yes** | none | Base64 Fernet key. `api/config.py`'s `Settings.fernet` property raises `RuntimeError` the first time it's accessed if this is empty — there is no silent fallback. |
| `SECRET_KEY` | Production | `dev-secret-change-in-prod` | Session cookie signing key. The app refuses to start in production (`ENVIRONMENT=production`) with the default value (`api/main.py` lifespan check). |
| `DB_URL` / `DATABASE_URL` | No | `sqlite:///./qi_stat_studio.db` | Both env var names are accepted aliases for the same setting (`AliasChoices` in `api/config.py`); `DB_URL` wins if both are set. |
| `AI_PROVIDER` | No | `openrouter` | `openrouter` \| `openai` \| `local`. |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | No | model: `anthropic/claude-sonnet-4-6` | Used when `AI_PROVIDER=openrouter`. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | No | model: `gpt-4o-mini` | Used when `AI_PROVIDER=openai`. |
| `LOCAL_API_BASE` / `LOCAL_API_KEY` / `LOCAL_MODEL` | No | base: `http://localhost:11434`, model: `llama3.1` | Used when `AI_PROVIDER=local` (e.g. Ollama). |
| `SMTP_HOST` / `SMTP_PORT` | No | `smtp.gmail.com` / `587` | Used for mentor-invite and deadline-reminder emails. |
| `SMTP_USER` / `SMTP_PASS` | No | empty | SMTP auth; login is skipped when `SMTP_USER` is empty. |
| `FROM_EMAIL` | No | `qi-stat-studio@example.com` | Sender address on outbound notification emails. |
| `COOKIE_SECURE` | No | `False` | Set `True` behind HTTPS in production so the session cookie gets the `Secure` flag. |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Comma-separated or JSON-array list of allowed browser origins. |
| `ENVIRONMENT` | No | `development` | Set to `production` to enforce the `SECRET_KEY` check above. |

Without SMTP credentials, share/reminder emails fail but the share link
itself is still created. See the `notification_status` field returned by
`POST /share/{project_id}/create` in {doc}`api-reference`.
