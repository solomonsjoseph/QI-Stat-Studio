# Testing

## Running the suites

```bash
# Backend (from the repo root)
FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q

# Frontend unit/component tests
cd web && npm run test

# Frontend end-to-end (Playwright)
cd web && npm run e2e
```

Run one file (or one test) directly when iterating — the project convention
is to run only the tests you touched, not the full suite, until you're ready
to confirm no regressions:

```bash
FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q tests/test_report.py -k limitations
```

### Why that specific dummy Fernet key

`FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=` is a syntactically
valid (but not secret) base64 Fernet key. It's required because
`settings.fernet` raises `RuntimeError` if `FERNET_KEY` is unset
(`api/config.py`), and upload/report code paths encrypt and decrypt through
it — tests that touch uploads at all need a real, working key, just not a
production one. The same value is reused in
`web/playwright.config.js`'s backend environment and hardcoded at the top of
most backend test modules that need it.

### Test database isolation

`tests/conftest.py` forces `DB_URL=sqlite:///./test_qi_stat_studio.db`
*before* the app or its settings are imported, deletes any stale copy of
that file up front, creates the full schema once per test session via
`Base.metadata.create_all`, and truncates every table before each individual
test — so tests never touch your dev database (`qi_stat_studio.db`) and
never leak state between tests, regardless of run order.

## What each backend test file covers

| File | Covers |
|---|---|
| `test_auth.py` | Register/login/logout, first-user-is-admin, session cookie, duplicate/bad-credential errors. |
| `test_project_lifecycle.py` | Project CRUD, owner scoping, pagination/ordering, archive vs. purge, legacy ownerless project claiming, resume hydration. |
| `test_intake_validation.py` | Intake schema validation, skip rules, "I'm not sure" handling, AI prefill redaction, audit logging on save. |
| `test_intake_share.py` | Intake answer persistence and Q10 mentor-email auto-share/deadline behavior. |
| `test_upload_lifecycle.py` | Upload metadata, preview rows, replace/delete, active-upload gating for analysis. |
| `test_data_quality.py` | Every data-quality rule: case inconsistency, missingness, outliers, time gaps, duplicate IDs, message wording. |
| `test_col_type_detection.py` | `detect_col_type` — ID/Yes-No/Number/Category/Date detection edge cases. |
| `test_excel_analysis_integration.py` | `.xlsx`/`.xls` upload round-trip into analysis. |
| `test_analyze_router.py` | `/analyze/run` and `/analyze/{id}/recommend`: template execution, code generation, failure logging, validation, recommendation ordering. |
| `test_analysis_validation.py` | Parameter/upload validation before a template ever runs. |
| `test_template_selection.py` | `select_template`'s full branch table — every Q2–Q6 combination that decides the recommendation. |
| `test_descriptive.py`, `test_before_after_mean.py`, `test_before_after_pct.py`, `test_time_series_templates.py` | Runtime behavior of all six templates: statistics, sub-test selection, figures, edge cases. |
| `test_interpretation.py` | Contract test: every template must return an `interpretation` key. |
| `test_codegen.py` | R/SPSS/SAS code generation across all six templates — asserts real code, not the "not yet implemented" placeholder. |
| `test_report.py` | DOCX/PDF auth, rendered content, intervention caption, acknowledged-flags Limitations, edit history, PHI-safe project-update sanitization. |
| `test_share_lifecycle.py` | Share create/revoke/regenerate, mentor view/comment, scoped report downloads, deadline-reminder notifications. |
| `test_ai_router.py` | PHI scrubbing across **all** message fields, provider/model selection, rate limiting, usage/error logging. |
| `test_phi_scrubber.py` | The scrubber itself: names, MRNs, SSNs, emails, dates, addresses, and the AI-chat integration point. |
| `test_settings.py` | Settings registry read/upsert. |
| `test_api_contracts.py` | Backward-compatibility contracts (legacy `params` rejection, request-ID propagation, secret-setting rejection). |
| `test_health_observability.py` | `/health`, `/readyz`, error envelopes, `/admin/failures`, sanitized failure context, admin-only access. |
| `test_database_constraints.py` | SQLite FK enforcement is actually on. |
| `test_production_serving.py` | `/api` prefix stripping and SPA static-file fallback routing. |
| `test_migration_parity.py` | `alembic upgrade head` schema matches `Base.metadata` column-for-column. |
| `test_migration_drift.py` | Pinned schema details (token length, FK behavior, nullability) that have broken before. |
| `test_full_journey.py` | One end-to-end backend regression: register → project → intake → upload → analyze → report package. |

## What each frontend test file covers

| File | Covers |
|---|---|
| `App.test.jsx` | Resume hydration from the URL and from the landing project list, server-interpretation mapping, step enabling, load-failure recovery. |
| `screens/ProjectDescription.test.jsx` | Guide-verbatim wording, PHI-redacted AI prefill state. |
| `screens/IntakeQuestions.test.jsx` | Guide wording, Q7 unsure-date handling, PHI banner. |
| `screens/Upload.test.jsx` | Upload flow, 5-row preview rendering (including null cells), context update. |
| `screens/DataReview.test.jsx` | Resumed-warning acknowledgement checkbox state. |
| `screens/AnalysisSelection.test.jsx` | Recommendation loading/ordering, recommended badge, fallback on API failure, Continue gating. |
| `screens/ParameterSelection.test.jsx` | Submit clears stale downstream results, resumed value-column state, active-template-only params. |
| `screens/Results.test.jsx` | Analysis run, AI interpretation load/error/fallback, retry, Edit & Review gating. |
| `screens/EditReview.test.jsx` | Save-edit sequencing/failure handling, resumed interpretation prefill. |
| `screens/DownloadShare.test.jsx` | Report-generation gate, preview content, download links, mentor-share affordance. |
| `screens/MentorView.test.jsx` | Mentor view load/retry, comment save failure, edit/delete via author email. |
| `screens/Settings.test.jsx` | Back-navigation to the correct previous wizard screen. |

## End-to-end (Playwright)

`web/e2e/critical-path.spec.js` is the one E2E spec: it walks the *entire*
resident journey against a real, running backend and frontend — register,
describe, all nine intake questions, upload a generated 12-row CSV, confirm
column types, acknowledge data-quality warnings, pick Run Chart, map
columns, view results, edit the report, download links, share with a
mentor, then switches to the mentor's view (in the same test) to confirm no
download links exist there, and posts a mentor comment.

It's gated behind an env var and skipped otherwise:

```bash
QISS_E2E=1 npm run e2e
```

By default Playwright expects the servers already running; set
`QISS_E2E_START_SERVER=1` to have Playwright's `webServer` config start
both for you (backend: `alembic upgrade head` against a fresh
`QISS_E2E_DB` — default `e2e_qi_stat_studio.db` — then `uvicorn`; frontend:
`npm run dev`). `baseURL` defaults to `http://127.0.0.1:5173`, one browser
project (`chromium`/Desktop Chrome), global timeout 120s.

## Continuous integration

There is currently no `.github/workflows/` (or other CI config) in this
repository — the three commands above are run manually / by whatever
external process your team wires up. If you add CI, run them in this order
(cheapest/most-isolated first): backend tests → frontend unit tests → E2E.
