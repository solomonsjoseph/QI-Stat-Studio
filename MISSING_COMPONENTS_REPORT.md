# Missing Components Report — Source-Only Audit

Source of truth used: `qi_stat_studio/` source files only. README claims were not treated as authoritative.

Verification performed:
- Backend tests: `FERNET_KEY=... PYTHONPATH=. python -m pytest -q` from `qi_stat_studio`
  - Result: `133 passed, 1 warning`
  - Warning: spaCy model `en_core_web_sm` 3.8.0 with spaCy runtime 3.7.4.
- Frontend production build: `npm run build` from `qi_stat_studio/web`
  - Result: build succeeded.
- Source contract checks:
  - `AnalysisRequest` rejects frontend-style `{ params: ... }`; requires `{ parameters: ... }`.
  - `EditIn` ignores frontend-sent `original_text`.

This report lists source-visible missing components, incomplete integrations, and gaps where the current code advertises or implies behavior but does not fully cover it.

---

## Executive Summary

The project has a working backend test suite and builds the React frontend, but the source shows several missing components that prevent the app from being complete as an end-to-end product.

Highest-impact missing components:

1. **Frontend analysis payload does not match backend schema.**
   - Frontend sends `params`.
   - Backend requires `parameters`.
   - Result: the main wizard likely cannot run analysis from the UI without a 422 validation error.

2. **Excel upload support is incomplete.**
   - Upload accepts `.xlsx` / `.xls`.
   - Analysis always reloads decrypted bytes with `pd.read_csv`.
   - Result: Excel uploads can be accepted but later fail during analysis.

3. **Report figures are not persisted into `analysis_runs.result_json`.**
   - Analysis deliberately excludes `figure_base64` from stored result JSON.
   - Report generation loads result JSON from the database and looks for `figure_base64`.
   - Result: downloaded DOCX/PDF reports likely omit figures even when the UI showed one.

4. **Project title/description editing is not actually persisted to the `Project` row after the initial placeholder project is created.**
   - Landing creates `New QI Project`.
   - Description screen only saves the description as intake `q1`.
   - Result: reports/share views can use placeholder or blank project metadata.

5. **Mentor sharing lacks email delivery, access controls, revocation, expiration, and identity.**
   - There is a notification stub only.
   - Share token is bearer access with no lifecycle.

6. **No authentication/authorization exists.**
   - Any client that can reach the API can list projects, get reports, add edits, create share links, view settings, etc.

7. **Frontend resume flow is not real project restoration.**
   - It loads only the first project ID.
   - It does not hydrate intake answers, upload state, selected template, results, or screen position.

8. **Database migration/schema drift exists.**
   - ORM says mentor token is `String(128), unique=True`.
   - Migration creates `String(64)` without unique constraint.
   - App also uses `Base.metadata.create_all`, which bypasses migration discipline.

9. **Settings are stored but mostly not wired into runtime behavior.**
   - `app_settings` is a raw key/value table.
   - Config still reads environment variables.
   - OpenRouter model setting in config is not used by the AI router default.

10. **No frontend tests or end-to-end tests cover the wizard.**
    - Backend tests pass because they call backend-native payloads.
    - They do not catch frontend/backend integration mismatches.

---

# 1. End-to-End Wizard Gaps

## 1.1 Critical: Frontend cannot reliably run analysis because request shape is wrong

### Current source

Frontend:

```js
runAnalysis: (projectId, uploadId, template, params) =>
  req('POST', '/analyze/run', { project_id: projectId, upload_id: uploadId, template, params }),
```

Source:
- `web/src/api.js`

Backend schema:

```py
class AnalysisRequest(BaseModel):
    project_id: int
    upload_id: int
    template: str
    parameters: Dict[str, Any]
```

Source:
- `api/models_api.py`

Backend route:

```py
def run_analysis(body: AnalysisRequest, db: Session = Depends(get_db)):
    ...
    params = dict(body.parameters)
```

Source:
- `api/routers/analyze.py`

### Missing component

A stable frontend/backend API contract for `/analyze/run`.

### Impact

The main user journey reaches `Results.jsx`, calls `api.runAnalysis(...)`, and sends `params`. Backend validation requires `parameters`. Pydantic validation rejects the frontend shape.

Observed validation:

```text
rejected ('parameters',) missing
```

### Required fix

Either:
- frontend sends `parameters: params`, or
- backend accepts both `parameters` and legacy/current frontend `params`.

Because this is a clean-cutover codebase, the better fix is to align the frontend with the backend schema and add an integration test that exercises the real frontend payload shape.

---

## 1.2 Critical: Excel upload is accepted but analysis reload assumes CSV

### Current source

Upload accepts:

```py
if suffix not in {".csv", ".xlsx", ".xls"}:
    raise HTTPException(400, f"Unsupported file type: {suffix}")
raw = await file.read()
df = pd.read_csv(io.BytesIO(raw)) if suffix == ".csv" else pd.read_excel(io.BytesIO(raw))
...
enc_path.write_bytes(settings.fernet.encrypt(raw))
```

Source:
- `api/routers/upload.py`

Analysis reloads:

```py
raw = settings.fernet.decrypt(open(upload.encrypted_path, "rb").read())
df = pd.read_csv(io.BytesIO(raw))
```

Source:
- `api/routers/analyze.py`

### Missing component

Persisted upload file type / parser metadata and matching reload logic.

### Impact

`.xlsx` and `.xls` files are accepted, encrypted, and stored. Later analysis decrypts the bytes and tries `pd.read_csv(...)`, which is wrong for Excel bytes.

### Required fix

Store file type on `Upload` or infer it safely from filename, then reload with:
- `pd.read_csv(...)` for CSV;
- `pd.read_excel(...)` for XLS/XLSX.

Also add an upload-to-analysis test for Excel.

---

## 1.3 Required: Wizard resume flow does not restore project state

### Current source

Landing resume button:

```js
onClick={() => api.listProjects().then(ps => ps.length && (update({ projectId: ps[0].id }), next()))}
```

Source:
- `web/src/screens/Landing.jsx`

API wrapper has unused project/intake getters:

```js
getProject: (id) => req('GET', `/projects/${id}`),
getAnswers: (projectId) => req('GET', `/intake/${projectId}`),
```

Source:
- `web/src/api.js`

Observed usage count:
- `api.getProject`: 0 frontend usages.
- `api.getAnswers`: 0 frontend usages.

### Missing component

Real project resume/hydration.

### Impact

Resume only sets `projectId` to the first project and moves to the next screen. It does not restore:
- project title;
- project description;
- intake answers;
- upload ID;
- uploaded column types;
- selected analysis template;
- parameters;
- last analysis run;
- current wizard step;
- report edits.

### Required fix

Add a proper project resume model:
- list projects with ordering;
- choose a specific project;
- fetch project details;
- fetch intake answers;
- fetch latest upload metadata;
- fetch latest analysis run;
- restore wizard screen based on project state.

---

## 1.4 Required: Browser refresh loses all wizard state

### Current source

Wizard state is in React memory:

```js
const [ctx, setCtx] = useState({})
```

Source:
- `web/src/App.jsx`

No local storage, server-side session state, or route-based step recovery exists.

### Missing component

Persistence/hydration of in-progress wizard state.

### Impact

Refreshing the page loses:
- selected screen;
- project ID unless on mentor route;
- upload ID;
- answers;
- template;
- parameters;
- run ID;
- AI interpretation;
- share state.

### Required fix

Persist minimal wizard state either:
- server-side using project-derived state, preferred; or
- client-side with local storage as a temporary convenience.

---

# 2. Project Management Gaps

## 2.1 Required: No project update endpoint

### Current source

Backend project routes:

```py
@router.post("")
def create_project(...)

@router.get("")
def list_projects(...)

@router.get("/{project_id}")
def get_project(...)

@router.post("/{project_id}/edits")
def save_edit(...)
```

Source:
- `api/routers/projects.py`

No `PUT /projects/{id}` or `PATCH /projects/{id}` exists.

### Missing component

Project update API.

### Impact

The initial project row is created with placeholder data:

```js
api.createProject({ title: 'New QI Project', description: '' })
```

Source:
- `web/src/screens/Landing.jsx`

Then the description screen collects title/description but does not update the `Project` row.

Source:
- `web/src/screens/ProjectDescription.jsx`

Reports and mentor views query `Project` fields.

Source:
- `api/routers/report.py`
- `api/routers/share.py`

Result: exported reports and mentor views can use stale placeholder project metadata.

### Required fix

Add:
- `PATCH /projects/{project_id}` with `title`, `description`, `status`, `deadline`;
- frontend call from `ProjectDescription.jsx`;
- tests for persisted title/description in reports and mentor view.

---

## 2.2 Required: No project delete/archive component

### Current source

There is no delete/archive endpoint in `api/routers/projects.py`.

### Missing component

Project lifecycle management:
- delete;
- archive;
- complete;
- cancel;
- restore.

### Impact

Projects accumulate indefinitely. Associated encrypted files under `uploads_enc/` also have no cleanup path.

### Required fix

Add a lifecycle decision:
- either soft-delete/archive via `status`;
- or hard-delete with cascading cleanup of uploads, encrypted files, analysis runs, shares, edits, audit logs.

---

## 2.3 Required: No project ownership or user identity

### Current source

`Project` has:

```py
id
title
description
status
deadline
created_at
```

Source:
- `api/models_db.py`

No user/account/owner fields exist.

### Missing component

User/project ownership model.

### Impact

Every project is globally visible through `GET /projects`.

Source:
- `api/routers/projects.py`

Any client can:
- list all projects;
- fetch any project by numeric ID;
- create edits;
- run analysis;
- generate reports.

### Required fix

Introduce at least one of:
- authenticated users and project ownership;
- single-site protected deployment with access controls outside the app;
- explicit local-only/no-auth product constraint documented and enforced.

---

## 2.4 Required: No pagination, ordering, or filtering for project list

### Current source

```py
return db.query(Project).all()
```

Source:
- `api/routers/projects.py`

### Missing component

List controls:
- ordering;
- pagination;
- filtering by status;
- limiting.

### Impact

Unbounded list endpoint and unpredictable resume behavior.

### Required fix

Add query params:
- `limit`;
- `offset`;
- `status`;
- `order_by=created_at desc`.

---

# 3. Intake and Recommendation Gaps

## 3.1 Required: `q1` exists only implicitly

### Current source

`ProjectDescription.jsx` saves:

```js
await api.saveAnswers(ctx.projectId, { q1: desc })
```

Source:
- `web/src/screens/ProjectDescription.jsx`

But `IntakeQuestions.jsx` begins at `q2`.

Source:
- `web/src/screens/IntakeQuestions.jsx`

### Missing component

Formal intake schema that includes all questions, including `q1`.

### Impact

`q1` is persisted as an intake answer but is not defined in the frontend question list. This makes the intake model implicit and easy to break.

### Required fix

Create a shared intake schema/contract:
- `q1` project description;
- `q2`-`q10` structured questions;
- per-question type and validation.

---

## 3.2 Required: `is_unsure` exists in database/API model but is unused

### Current source

Database:

```py
is_unsure = Column(Boolean, default=False)
```

Source:
- `api/models_db.py`

API model:

```py
class IntakeAnswerIn(BaseModel):
    question_key: str
    answer: str
    is_unsure: bool = False
```

Source:
- `api/models_api.py`

But save endpoint uses a generic dict:

```py
class AnswerPayload(BaseModel):
    answers: dict
```

Source:
- `api/routers/intake.py`

Frontend stores unsure as answer text, not `is_unsure`.

Source:
- `web/src/screens/IntakeQuestions.jsx`

### Missing component

Actual `is_unsure` handling.

### Impact

The database has a field that never gets meaningful data. Recommendation logic relies on string matching against answers rather than structured uncertainty.

### Required fix

Either:
- remove `is_unsure`; or
- make intake answers structured and use `is_unsure` in recommendation/reporting.

---

## 3.3 Required: Backend accepts arbitrary intake keys and shapes

### Current source

```py
for key, value in payload.answers.items():
    stored = json.dumps(value) if isinstance(value, dict) else str(value)
    _upsert(db, project_id, key, stored)
```

Source:
- `api/routers/intake.py`

### Missing component

Backend intake validation.

### Impact

Backend accepts:
- unknown question keys;
- invalid option values;
- malformed composite answers;
- invalid dates;
- invalid email fields;
- nonnumeric `q6`.

Recommendation later does:

```py
q6 = int(answers.get("q6", 0) or 0)
```

Source:
- `api/routers/analyze.py`

Invalid `q6` can raise.

### Required fix

Add typed Pydantic intake schema or per-question validation.

---

## 3.4 Required: Frontend-only skip logic is not enforced server-side

### Current source

Frontend skips `q7` and `q8` when `q3` is no-comparison:

```js
const visible = QUESTIONS.filter(
  q => !(( q.key === 'q7' || q.key === 'q8') && answers.q3 === NO_COMPARISON)
)
```

Source:
- `web/src/screens/IntakeQuestions.jsx`

Backend stores whatever it receives.

Source:
- `api/routers/intake.py`

### Missing component

Canonical intake flow rules on backend.

### Impact

API clients can store impossible/inconsistent intake states.

### Required fix

Move flow constraints into shared schema or backend validation.

---

## 3.5 Required: AI intake prefill is unvalidated and lossy

### Current source

Frontend asks AI for JSON, then parses the first JSON-looking object.

Source:
- `web/src/screens/ProjectDescription.jsx`

### Missing component

Structured AI response validation and mapping to actual allowed option strings.

### Impact

AI can return short labels like `"percent"` or `"yes"` that do not match the exact option strings used by recommendation logic, which expects substring matches against stored answer text.

### Required fix

Normalize AI suggestions into canonical allowed options before storing/displaying.

---

# 4. Upload and Data Quality Gaps

## 4.1 Critical: Upload does not verify the project exists

### Current source

Upload route stores an `Upload(project_id=project_id, ...)` without checking `Project`.

Source:
- `api/routers/upload.py`

### Missing component

Foreign project validation.

### Impact

Uploads can be created for nonexistent project IDs. SQLite may not enforce foreign keys unless explicitly enabled. Source does not enable SQLite foreign key PRAGMA.

### Required fix

Check `Project` exists before storing upload.

---

## 4.2 Critical: Uploaded filename is used directly in encrypted path

### Current source

```py
enc_path = UPLOAD_DIR / f"{project_id}_{file.filename}.enc"
enc_path.write_bytes(settings.fernet.encrypt(raw))
```

Source:
- `api/routers/upload.py`

### Missing component

Filename sanitization and safe storage naming.

### Impact

User-controlled `file.filename` can contain path separators or unusual names. At minimum this can break storage. At worst it can write outside the intended directory if path traversal is accepted by the platform/path handling.

### Required fix

Ignore user filename for disk path. Use generated ID/UUID:
- store original filename separately for display;
- write encrypted bytes to `uploads_enc/{upload_id or uuid}.enc`.

---

## 4.3 Required: File size validation depends on `UploadFile.size`

### Current source

```py
if file.size and file.size > MAX_BYTES:
    raise HTTPException(400, "File exceeds 50 MB limit")
raw = await file.read()
```

Source:
- `api/routers/upload.py`

### Missing component

Actual byte-length enforcement after reading or streamed enforcement while reading.

### Impact

If `file.size` is unavailable or inaccurate, large files can be read fully into memory.

### Required fix

Check `len(raw)` after reading, or stream with a byte cap.

---

## 4.4 Required: Parser errors are not handled cleanly

### Current source

```py
df = pd.read_csv(io.BytesIO(raw)) if suffix == ".csv" else pd.read_excel(io.BytesIO(raw))
```

Source:
- `api/routers/upload.py`

No try/except converts pandas parser errors into user-friendly 400s.

### Missing component

Upload parse error handling.

### Impact

Malformed CSV/XLSX can return 500 or opaque errors.

### Required fix

Catch parser errors and return 400 with actionable message.

---

## 4.5 Required: Empty datasets and empty columns are not explicitly rejected

### Current source

Upload immediately computes summaries and stores the upload.

Source:
- `api/routers/upload.py`

No check for:
- zero rows;
- zero columns;
- duplicate column names;
- all-empty file;
- unsupported encodings.

### Missing component

Dataset shape validation.

### Impact

Later templates can fail with unclear 500s.

### Required fix

Validate:
- at least one row;
- at least one column;
- unique columns;
- required candidate columns for selected analysis later.

---

## 4.6 Required: Column type confirmation stores the wrong shape

### Current source

Frontend sends `{ col_types: colTypes }`; backend stores `json.dumps(body)` directly.

Sources:
- `web/src/api.js`
- `api/routers/upload.py`

### Missing component

Stable column-type update contract.

### Impact

Initial upload stores a direct mapping; column confirmation likely stores nested `{"col_types": {...}}`.

### Required fix

Use the `ColumnTypeUpdate` model or define a correct payload:
- frontend sends raw mapping, or
- backend extracts `body["col_types"]`.

---

## 4.7 Required: `column_map` exists but is unused

### Current source

Database has `column_map`; API has `ColumnTypeUpdate.column_map`; implementation only manipulates `col_types`.

Sources:
- `api/models_db.py`
- `api/models_api.py`
- `api/routers/upload.py`

### Missing component

Column mapping feature.

### Impact

The schema implies support for mapping source columns to semantic roles, but implementation only stores detected UI column types.

### Required fix

Either remove `column_map` or implement source-column-to-analysis-role mapping.

---

## 4.8 Required: Data quality acknowledgements are stored but not consistently used

### Current source

Frontend requires warning acknowledgement. Backend stores acknowledged warning flags. Report uses acknowledged flags if present. Analysis still blocks >30% missingness in selected outcome column regardless of acknowledgement.

Sources:
- `web/src/screens/DataReview.jsx`
- `api/routers/upload.py`
- `api/routers/report.py`
- `api/routers/analyze.py`

### Missing component

Clear policy connecting acknowledgement to analysis.

### Impact

The analysis error says to return to Data Review to acknowledge or choose another column, but acknowledgement does not allow analysis to proceed.

### Required fix

Decide policy:
- warnings acknowledgeable, hard outcome missingness not overrideable; update message; or
- allow override if explicitly acknowledged.

---

## 4.9 Required: No upload retrieval, replacement, deletion, or cleanup lifecycle

### Current source

Upload routes only support create upload, update col types, and save acknowledged flags.

Source:
- `api/routers/upload.py`

### Missing component

Upload lifecycle:
- list uploads for project;
- get upload metadata;
- replace upload;
- delete upload and encrypted file;
- cleanup orphan files.

### Impact

Uploads and encrypted files accumulate and cannot be managed.

---

# 5. Statistical Analysis Gaps

## 5.1 Required: No parameter validation before template execution

Templates directly index required params and dataframe columns.

Sources:
- `api/templates/*.py`
- `api/routers/analyze.py`

### Missing component

Template-specific Pydantic parameter schemas.

### Impact

Missing parameters or wrong types become exceptions and 500s.

### Required fix

Add schema validation per template:
- required fields;
- column exists in uploaded dataframe;
- numeric/date compatibility;
- optional fields;
- friendly 400 errors.

---

## 5.2 Required: Numeric/date coercion failures are not handled cleanly

Templates coerce dates/numbers but do not validate enough usable data remains.

Sources:
- `api/templates/run_chart.py`
- `api/templates/p_chart.py`
- `api/templates/u_c_chart.py`
- `api/templates/before_after_pct.py`

### Missing component

Post-coercion data sufficiency checks.

### Impact

Bad date/numeric data can lead to empty series, NaNs, invalid charts, or unclear exceptions.

### Required fix

Validate minimum non-null counts, groups/time points, denominators, and pre/post group presence.

---

## 5.3 Required: Minimum sample/time-point rules are recommendation-only, not enforced

Recommendation prefers control charts with `q6 >= 12`, but templates do not enforce minimum counts.

Sources:
- `api/routers/analyze.py`
- `api/templates/*.py`

### Missing component

Analysis validity checks.

### Impact

A user can manually choose `p_chart` or `u_c_chart` with too few time points.

### Required fix

Add validation/warnings or explicit override policy.

---

## 5.4 Required: Generated R/SPSS/SAS code can diverge from actual Python analysis

Python analysis chooses tests dynamically; generated code often emits simplified static snippets.

Sources:
- `api/templates/before_after_mean.py`
- `api/templates/codegen.py`

### Missing component

Code supplement parity with actual analysis.

### Impact

The report's code supplement may not reproduce the exact analysis the app performed.

### Required fix

Generate code from actual result/test decision, not only template + params.

---

## 5.5 Required: p-chart and u-chart denominator support is incomplete in code generation

Runtime templates support denominator columns; codegen often ignores them.

Sources:
- `api/templates/p_chart.py`
- `api/templates/u_c_chart.py`
- `api/templates/codegen.py`

### Missing component

Codegen support for denominator-based p-charts and u-charts.

### Impact

Report code supplement can be wrong for denominator-based analyses.

### Required fix

Generate separate code paths for denominator and non-denominator cases.

---

## 5.6 Required: Before/after templates have edge-case holes

Before/after proportion can fail with empty/incomplete contingency tables or zero cells. Before/after mean can fail with missing groups, too few observations, or all-null values.

Sources:
- `api/templates/before_after_pct.py`
- `api/templates/before_after_mean.py`

### Missing component

Robust precondition validation.

### Required fix

Validate sample sizes, group presence, outcome levels, and zero-cell cases before running tests.

---

## 5.7 Required: Run chart signal detection is minimal

Run chart only checks longest run on one side of the median.

Source:
- `api/templates/run_chart.py`

### Missing component

Full run-chart rule set, if intended by the domain.

### Impact

Other common signals are not covered: trends, astronomical points, too many/few runs, and median-tie handling.

---

# 6. Report Generation Gaps

## 6.1 Critical: Figures are not included in downloaded reports

Analysis returns `figure_base64` to frontend, but stores result JSON excluding it. Report builder later looks for `figure_base64` in stored result JSON.

Sources:
- `api/routers/analyze.py`
- `api/routers/report.py`

### Missing component

Figure persistence or figure regeneration for reports.

### Impact

The frontend can show the figure immediately after analysis, but downloaded DOCX/PDF likely omit it.

### Required fix

Store figures separately, store `figure_base64`, or regenerate figures at report time.

---

## 6.2 Required: Edited report title is not used by report generation

Frontend saves title edits. Report title uses `project.title`.

Sources:
- `web/src/screens/EditReview.jsx`
- `api/routers/report.py`

### Missing component

Report field override application for title.

### Required fix

When building report context, apply latest edits for title, caption, and interpretation. Currently only interpretation is applied.

---

## 6.3 Required: Figure caption edit is collected but unused

Frontend collects `caption`; report builder never reads `field="caption"`.

Sources:
- `web/src/screens/EditReview.jsx`
- `api/routers/report.py`

### Missing component

Caption persistence/use in report.

---

## 6.4 Required: `original_text` is sent by frontend but ignored by backend

Frontend sends `original_text`; backend schema ignores it and stores `original_text=""`.

Sources:
- `web/src/screens/EditReview.jsx`
- `api/models_api.py`
- `api/routers/projects.py`

### Missing component

Edit audit fidelity.

### Required fix

Add `original_text` to `EditIn` and store it.

---

## 6.5 Required: Report context chooses first upload, not the upload used for the run

Report builder uses first upload for project. `AnalysisRun` does not store `upload_id`.

Sources:
- `api/routers/report.py`
- `api/models_db.py`

### Missing component

AnalysisRun-to-Upload relationship.

### Impact

If a project has multiple uploads, the report can show limitations/source file from the wrong upload.

---

## 6.6 Required: Report does not include mentor comments or full audit log

Mentor comments and audit log rows exist but are not included in report generation.

Sources:
- `api/models_db.py`
- `api/routers/share.py`
- `api/routers/report.py`

### Missing component

Optional mentor feedback section and complete audit log export.

---

# 7. AI / PHI Gaps

## 7.1 Required: Configured OpenRouter model is not used by default

Config defines `openrouter_model`, but `ChatRequest` defaults to `openai/gpt-4o-mini` and the router uses `req.model`.

Sources:
- `api/config.py`
- `api/routers/ai.py`

### Missing component

Runtime model configuration wiring.

### Required fix

Make `ChatRequest.model` optional and default to `settings.openrouter_model`.

---

## 7.2 Required: No structured AI response contract

Project description asks the model to return JSON, then parses with a regex.

Source:
- `web/src/screens/ProjectDescription.jsx`

### Missing component

Structured output validation.

### Impact

AI can return invalid JSON or valid JSON with invalid option labels.

---

## 7.3 Required: PHI scrubber loading is a hard import-time dependency

```py
_nlp = spacy.load("en_core_web_sm")
```

Source:
- `api/middleware/phi_scrubber.py`

### Missing component

Graceful startup handling for missing spaCy model.

---

## 7.4 Required: PHI scrubbing coverage is limited

Regex covers MRN, SSN, phone, email, DOB; spaCy redacts PERSON, DATE, ORG.

Source:
- `api/middleware/phi_scrubber.py`

### Missing component

Comprehensive PHI detection policy.

Possible missed PHI includes addresses, ZIP codes, account numbers, facility/unit names, order numbers, device IDs, and other identifiers.

---

## 7.5 Required: No AI rate limiting, retry policy, or cost guardrails

AI router only has a single `httpx.post(..., timeout=30)` call.

Source:
- `api/routers/ai.py`

### Missing component

AI integration resilience and cost control.

---

# 8. Mentor Sharing Gaps

## 8.1 Required: Email notification is only a stub

Source:
- `api/routers/notifications.py`

### Missing component

Actual email sending.

### Impact

Mentor email and deadline are collected, but no email is sent.

---

## 8.2 Required: No share token expiration or revocation

`MentorShare` has token, mentor email, and comments JSON. No lifecycle fields.

Source:
- `api/models_db.py`

### Missing component

Share lifecycle: created, expires, revoked, regenerated.

---

## 8.3 Required: No mentor identity/authentication

Comment author is arbitrary/defaulted.

Sources:
- `api/routers/share.py`
- `web/src/screens/MentorView.jsx`

### Missing component

Mentor identity model.

---

## 8.4 Required: Mentor view is result-summary only

Mentor view does not return table, figure, limitations, code supplement, report downloads, or full interpretation.

Source:
- `api/routers/share.py`

### Missing component

Complete mentor review package.

---

## 8.5 Required: Mentor comments are stored as JSON text, not normalized records

Source:
- `api/models_db.py`
- `api/routers/share.py`

### Missing component

`MentorComment` table with IDs, timestamps, author metadata, edit/delete support.

---

# 9. Settings / Configuration Gaps

## 9.1 Required: Settings UI writes database values that runtime config does not read

Settings router stores arbitrary key/value rows. Runtime config reads environment/.env.

Sources:
- `api/routers/settings_router.py`
- `api/config.py`

### Missing component

Connection between app settings and actual runtime behavior.

---

## 9.2 Critical: Settings endpoint has no access control and can expose secrets if used for secrets

Source:
- `api/routers/settings_router.py`

### Missing component

Secure settings boundary.

---

## 9.3 Required: Settings keys are unvalidated

Source:
- `api/routers/settings_router.py`

### Missing component

Typed settings registry with allowed keys, value types, validation, and visibility rules.

---

# 10. Security and Privacy Gaps

## 10.1 Critical: No authentication

No auth middleware, login route, user model, session model, JWT validation, or dependency guard exists.

Sources:
- `api/main.py`
- `api/routers/*.py`
- `api/models_db.py`

### Missing component

Authentication system.

---

## 10.2 Critical: No authorization

Routes use raw numeric IDs and no ownership checks.

Sources:
- `api/routers/*.py`

### Missing component

Authorization policy.

---

## 10.3 Critical: Report endpoints are public by run ID

Source:
- `api/routers/report.py`

### Missing component

Report access control.

---

## 10.4 Critical: Share links are bearer tokens with no scope controls

Source:
- `api/routers/share.py`

### Missing component

Scoped/limited share access.

---

## 10.5 Required: CORS is dev-only

```py
allow_origins=["http://localhost:5173"]
```

Source:
- `api/main.py`

### Missing component

Production CORS configuration.

---

## 10.6 Required: Default `secret_key` is insecure and unused

Source:
- `api/config.py`

### Missing component

Secret management policy.

---

# 11. Database and Migration Gaps

## 11.1 Required: App uses `create_all` at import/startup

Source:
- `api/main.py`

### Missing component

Migration-controlled schema management.

---

## 11.2 Required: Base Alembic revision is empty

Source:
- `alembic/versions/cc61920dee93_initial_schema.py`

### Missing component

Clean migration history.

---

## 11.3 Critical: ORM and migration disagree on mentor token column

ORM:
- `String(128)`
- `unique=True`

Migration:
- `String(64)`
- no unique constraint

Sources:
- `api/models_db.py`
- `alembic/versions/5be9d78e473c_initial_schema_full.py`

### Missing component

Schema consistency.

---

## 11.4 Required: No foreign key cascade behavior

Source:
- `api/models_db.py`

### Missing component

Data lifecycle/cascade policy.

---

## 11.5 Required: SQLite foreign key enforcement is not explicitly enabled

Source:
- `api/database.py`

### Missing component

SQLite FK enforcement.

---

# 12. Deployment and Runtime Gaps

## 12.1 Required: Dockerfile does not build frontend

Dockerfile expects frontend build to happen before Docker build.

Source:
- `Dockerfile`

### Missing component

Self-contained production Docker build.

---

## 12.2 Required: Docker database env var does not match settings field

Dockerfile uses `DATABASE_URL`; app config uses `db_url`; Alembic/env example use `DB_URL`.

Sources:
- `Dockerfile`
- `api/config.py`
- `alembic/env.py`
- `.env.example`

### Missing component

Consistent database configuration naming.

---

## 12.3 Required: No health endpoint

No `/health`, `/healthz`, or `/readyz` route exists.

Source:
- `api/routers/*.py`

### Missing component

Operational health check.

---

## 12.4 Required: No production logging/error handling layer

Source:
- `api/main.py`

### Missing component

Production diagnostics: structured logging, request IDs, global exception normalization.

---

# 13. Frontend Architecture and UX Gaps

## 13.1 Required: No real routing for wizard screens

Screen is local state; mentor route is manually detected from `window.location.pathname`.

Source:
- `web/src/App.jsx`

### Missing component

Route model or state restoration.

---

## 13.2 Required: Settings “Back” always goes to landing

Source:
- `web/src/screens/Settings.jsx`

### Missing component

Return-to-previous-screen behavior.

---

## 13.3 Required: Direct `fetch` bypasses API wrapper

`EditReview.jsx` posts directly instead of using `web/src/api.js`.

Source:
- `web/src/screens/EditReview.jsx`

### Missing component

Centralized API function for project edits.

---

## 13.4 Required: Frontend error handling is inconsistent

Some screens show errors; others do not catch network failures.

Sources:
- `web/src/screens/*.jsx`

### Missing component

Consistent UI error handling.

---

## 13.5 Required: No loading/disabled safeguards on several actions

Examples:
- share creation;
- mentor comment submit;
- settings save;
- edit save response checking.

Sources:
- `web/src/screens/*.jsx`

### Missing component

Consistent action state model.

---

## 13.6 Required: Accessibility is basic and incomplete

Source uses plain Tailwind/JSX forms but no systematic accessibility pass.

Sources:
- `web/src/screens/*.jsx`

### Missing component

Accessibility review: focus management, error announcements, keyboard flow, progress indicator.

---

# 14. Testing Gaps

## 14.1 Critical: Backend tests do not catch frontend/backend `/analyze/run` mismatch

Backend tests send `parameters`; frontend sends `params`.

Sources:
- `tests/test_analyze_router.py`
- `web/src/api.js`

### Missing component

Cross-layer contract test.

---

## 14.2 Required: No frontend tests

`web/package.json` has no test script.

Source:
- `web/package.json`

### Missing component

Frontend unit/component tests.

---

## 14.3 Required: No end-to-end test for the full resident journey

Backend tests and frontend build exist; no source indicates browser E2E tests.

Sources:
- `tests/`
- `web/package.json`

### Missing component

E2E test covering: start project, intake, upload, review, analysis, edit, report, share.

---

## 14.4 Required: No Excel upload-to-analysis test

Sources:
- `api/routers/upload.py`
- `api/routers/analyze.py`

### Missing component

Excel integration test.

---

## 14.5 Required: No report-figure persistence test

Sources:
- `api/routers/analyze.py`
- `api/routers/report.py`

### Missing component

Report content regression test proving figures appear in DOCX/PDF.

---

## 14.6 Required: No tests for edited title/caption in report

Source:
- `api/routers/report.py`

### Missing component

Edit application tests for title, caption, and interpretation.

---

## 14.7 Required: No migration drift test

Sources:
- `api/models_db.py`
- `alembic/versions/5be9d78e473c_initial_schema_full.py`

### Missing component

Migration/schema consistency test.

---

# 15. Observability and Audit Gaps

## 15.1 Required: FailureLog is minimal and not exposed

Source:
- `api/models_db.py`
- `api/routers/analyze.py`

### Missing component

Failure diagnostics: message, route/action, project/upload/run IDs, safe stack/context, correlation ID, admin retrieval.

---

## 15.2 Required: AuditLog is inconsistent

Logged:
- project created;
- field edited;
- PHI redacted.

Not logged:
- upload;
- data quality acknowledgement;
- template selection;
- analysis run;
- report download;
- share creation;
- mentor comment;
- settings change.

Sources:
- `api/routers/projects.py`
- `api/routers/ai.py`
- `api/routers/*.py`

### Missing component

Consistent audit policy.

---

## 15.3 Required: No request IDs or correlation IDs

Source:
- `api/main.py`

### Missing component

Traceability middleware.

---

# 16. API Design Gaps

## 16.1 Required: API schemas are partial and duplicated inline

Some schemas are in `api/models_api.py`; others are inline in routers.

Sources:
- `api/models_api.py`
- `api/routers/*.py`

### Missing component

Centralized, complete API contract.

---

## 16.2 Required: Response models are missing on many routes

Sources:
- `api/routers/*.py`

### Missing component

Typed response contracts.

---

## 16.3 Required: Error response shape is not standardized

Sources:
- `api/routers/*.py`

### Missing component

Standard error envelope with code, message, field errors, and request ID.

---

# 17. Data Model Gaps

## 17.1 Required: AnalysisRun does not store upload ID

Source:
- `api/models_db.py`

### Missing component

Run-to-upload lineage.

---

## 17.2 Required: AnalysisRun does not store created timestamp

Source:
- `api/models_db.py`

### Missing component

Run history metadata.

---

## 17.3 Required: Upload does not store created timestamp or file type

Source:
- `api/models_db.py`

### Missing component

Upload metadata: created_at, file type, size, checksum, original filename, safe storage key.

---

## 17.4 Required: Mentor comments have no timestamp

Source:
- `api/routers/share.py`

### Missing component

Comment timestamp.

---

# 18. Source Hygiene / Dead or Misleading Components

## 18.1 Required: `notifications` module is imported but not wired as a router

Sources:
- `api/main.py`
- `api/routers/notifications.py`

### Missing component

Actual notification API/scheduler or removal of dead import.

---

## 18.2 Required: `ColumnTypeUpdate` model is not used correctly

Source:
- `api/routers/upload.py`

### Missing component

Actual use of typed request model.

---

## 18.3 Required: `AIRequest` model is unused

Sources:
- `api/models_api.py`
- `api/routers/ai.py`

### Missing component

Model cleanup or reuse.

---

## 18.4 Required: `MentorComment` model in `models_api.py` does not match share router payload

Sources:
- `api/models_api.py`
- `api/routers/share.py`

### Missing component

Single canonical mentor comment schema.

---

# 19. Prioritized Remediation Plan

## Critical path to make the app end-to-end functional

1. Fix `/analyze/run` payload mismatch.
2. Fix Excel analysis reload.
3. Persist or regenerate figures for reports.
4. Persist project title/description.
5. Apply report edits fully.
6. Add `upload_id` and timestamps to `AnalysisRun`.
7. Add minimum parameter/column validation for all templates.
8. Add one full E2E test for the resident wizard.

## Security hardening before real PHI/project use

1. Add authentication.
2. Add authorization by project.
3. Protect report endpoints.
4. Add share token expiry/revocation.
5. Sanitize upload filenames.
6. Secure settings endpoint.
7. Expand PHI scrubber or document its limits.
8. Add audit policy for upload/analyze/report/share/settings actions.

## Operational readiness

1. Remove production `create_all`; rely on Alembic.
2. Fix migration drift.
3. Standardize `DB_URL` / `DATABASE_URL`.
4. Add health/readiness endpoints.
5. Add structured logging/request IDs.
6. Make Docker build frontend assets itself.

---

# Final Assessment

The current source contains the core skeleton of the product:

- project creation;
- intake collection;
- upload/encryption;
- six statistical templates;
- AI proxy with PHI scrubbing;
- report generation;
- mentor share links;
- settings storage;
- backend tests.

But the missing components above mean it is not yet a complete, production-safe, end-to-end resident workflow. The most urgent issues are contract and lineage gaps that can break the primary path or produce incomplete reports.
