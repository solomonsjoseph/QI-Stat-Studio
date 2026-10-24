# Architecture decisions

Why things are built the way they are: the reasoning past choices, so future
maintainers don't have to re-derive it from scratch. Kept together on one
page given this project's size; if the codebase grows enough to warrant it,
split into `docs/decisions/ADR-NNN-*.md` per the usual one-file-per-decision
convention.

## ADR-001: SQLite as the database, with Alembic owning schema

**Status:** Accepted

**Context:** Single-clinic deployment scale (one Rutgers IM Clinic
instance), a small resident/mentor user base, and a strong preference for
zero external infrastructure to stand up.

**Decision:** SQLite via SQLAlchemy, with Alembic as the sole source of
truth for schema (the app never calls `Base.metadata.create_all()` outside
tests; see {doc}`data-model`).

**Consequences:** Deployment is a single file plus a migration step, with no
database server to provision or operate. `PRAGMA foreign_keys=ON` has to be
set explicitly per-connection (SQLite doesn't default to enforcing FKs), and
schema changes must go through `op.batch_alter_table(...)` since SQLite's
`ALTER TABLE` support is limited (every migration in this repo already
follows that pattern). If usage ever crosses single-instance concurrent
writers, this decision should be revisited. Nothing in the ORM layer
prevents swapping `DB_URL` to Postgres, but nothing has been tested against
it either.

## ADR-002: Real email/password sessions, not mock auth or Rutgers SSO

**Status:** Accepted (supersedes an earlier v1 mock-auth plan)

**Context:** The original product plan scoped v1 to a mock "Enter as
Resident" button, deferring real accounts and Rutgers SSO to a later phase.

**Decision:** The shipped app instead implements real accounts:
PBKDF2-HMAC-SHA256 password hashing, server-side sessions with a signed
cookie, and role-based access (`resident`/`admin`). See {doc}`architecture`
for the exact mechanics.

**Consequences:** Multiple residents can safely share one deployment with
real project isolation (`require_project_owner`), which a mock single-user
auth flow couldn't provide. Rutgers SSO integration (SAML2/OIDC) is a
deliberately deferred future phase, not a bug fix waiting to happen; there's
no SSO code path to finish, only one to add when it's prioritized.

## ADR-003: Fernet symmetric encryption for uploads, not a KMS

**Status:** Accepted

**Context:** Uploaded CSV/Excel files may contain de-identified clinical
data; at-rest protection is required, but the deployment target has no
managed key-management service.

**Decision:** A single `FERNET_KEY` (symmetric, in the environment)
encrypts every upload before it touches disk, via `cryptography.fernet`.

**Consequences:** Simple to operate: one key, one env var, required at
startup (`RuntimeError` if missing, never a silent no-encryption fallback).
The tradeoff is that key rotation is a manual, whole-fleet operation (no
per-file key versioning), and losing the key means losing every encrypted
upload, so back up `FERNET_KEY` with the same rigor as the database itself.

## ADR-004: PHI scrubbing is defense-in-depth, not a compliance guarantee

**Status:** Accepted

**Context:** The app must never forward identifiable patient data to a
third-party AI provider, but clinical free text (project descriptions, chat
messages) can't be perfectly structured in advance.

**Decision:** Combine cheap, fast regex patterns (MRN/SSN/phone/email/date/
address shapes) with spaCy NER (`PERSON`/`DATE`/`ORG`) as a second pass,
applied to every string field sent toward an LLM. See {doc}`security`. The
scrubber's own docstring is explicit that this is defense-in-depth, not a
certified de-identification pipeline.

**Consequences:** Fast (no external call needed to scrub), works even if
spaCy's model fails to load (regex-only fallback, logged), and is backed by
an architectural guarantee that full spreadsheet rows are never in the AI
request path at all, regardless of scrubbing. It's not a substitute for
resident discipline about what gets typed into free-text fields; the UI
says so directly (see the {doc}`../user-guide/concepts` privacy section).

## ADR-005: Mentor shares are view-only (downloads were built, then removed)

**Status:** Accepted (supersedes an earlier download-enabled design)

**Context:** An earlier iteration allowed mentors to download the DOCX/PDF
report from their share link.

**Decision:** Mentor report downloads were deliberately removed. The
mentor-view API response never includes a downloadable file, and the legacy
download route is hard-wired to return `404` for any format: a permanent
answer to old links, not a temporary gap (see {doc}`api-reference`,
{doc}`security`).

**Consequences:** Reports are unambiguously the resident's own artifact,
reviewed and commented on by a mentor but never redistributed as a file
from someone else's link. Anyone building a feature that touches mentor
sharing should treat "mentors cannot download" as a firm product boundary,
not an oversight to fix.

## ADR-006: Mentor comments are a normalized table, not a JSON blob

**Status:** Accepted (supersedes `mentor_shares.comments_json`)

**Context:** An earlier schema stored all of a share's comments as one JSON
array column on `mentor_shares`.

**Decision:** Migration `c4e1f8a2d9b6` drops `comments_json` in favor of a
proper `mentor_comments` table, one row per comment, with its own timestamps
and soft-delete (`deleted_at`).

**Consequences:** Editing or deleting a single comment is a normal `UPDATE`/
soft-delete on one row instead of read-modify-write surgery on a shared JSON
array, which risks lost updates under concurrent mentor edits. Per-comment
audit and query (e.g. "comments since X") also becomes possible without
deserializing the whole blob.

## ADR-007: Template selection uses one Q6 threshold, not a third band

**Status:** Accepted

**Context:** `select_template`'s time-series branch (`api/routers/analyze.py`)
recommends a control chart (p-chart/u-chart/c-chart) at 12+ time points and
a run chart below that: a single boundary, no intermediate "still a run
chart but with extra warnings" band.

**Decision:** Keep the single 12-point threshold as the validated contract.
Q6's UI helper text in `IntakeQuestions.jsx` should describe this exact
behavior and nothing more; it drifted once to imply a second threshold at
10, and was corrected back to match the algorithm below.

**Consequences:** Anyone touching `select_template` or Q6's helper text
should treat the single-threshold behavior as the source of truth, not a
simplification to fix by adding a second branch. A second threshold would
be a real behavior change requiring its own design sign-off, not a copy
edit.

## ADR-008: AI provider is pluggable via LiteLLM, never hardcoded to one vendor

**Status:** Accepted

**Context:** Clinics may have different institutional AI vendor
relationships (or none), and local/offline model hosting (Ollama) should be
a first-class option, not an afterthought.

**Decision:** All AI calls go through `litellm.completion(...)`, with
`AI_PROVIDER` selecting OpenRouter, OpenAI, or a local OpenAI-compatible
endpoint at runtime (admin-editable without a restart; see {doc}`how-to`).

**Consequences:** Swapping providers is a settings change, not a code
change. Core analysis functionality (upload, run charts, control charts,
statistical tests, reports) has zero dependency on any AI provider being
configured at all; only the two AI endpoints degrade gracefully to
"unavailable" without credentials.

## ADR-009: Statistical test selection is automatic, never resident-chosen

**Status:** Accepted

**Context:** The product's entire premise is that residents shouldn't need
to know when to use a t-test vs. Wilcoxon, or chi-square vs. Fisher's exact.

**Decision:** Every template that has a test-selection decision makes it
from the data itself. Before/after mean uses Shapiro-Wilk (normality) plus
Levene (variance equality) to choose t-test vs. Wilcoxon; before/after
proportion uses expected cell counts (`scipy.stats.chi2_contingency`) to
choose chi-square vs. Fisher's exact; u-chart vs. c-chart is chosen from
whether the aggregated denominator is stable across periods. See
{doc}`api-reference`'s `analyze` section and the template runners in
`api/templates/` for the exact thresholds.

**Consequences:** The resident never sees, or needs to answer, a "which
test?" question. That's the app's north star. It also means the exported
R/SPSS/SAS code (Q9) has to encode the *runtime* decision as a comment/branch
rather than a static script, since the "right" test depends on the
resident's actual data, not the template alone (see `api/templates/codegen.py`).

## ADR-010: Exported code is documentation, never executed by the app

**Status:** Accepted

**Context:** Q9 lets a resident export the completed analysis as R, SPSS, or
SAS code "for your supplement or mentor."

**Decision:** That code is generated text only. The app never shells out to
an R/SPSS/SAS interpreter, and the exported code is not required to
reproduce the analysis bit-for-bit; it's a readable supplement, not a
guaranteed-reproducible pipeline.

**Consequences:** No code-execution sandbox, no per-language runtime
dependency, and no attack surface from executing resident- or
mentor-influenced code server-side. The tradeoff is that the generated code
and the app's actual computed result can, in principle, drift if a template
runner changes without its matching `codegen.py` branch being updated in the
same change. `tests/test_codegen.py` exists specifically to catch that
drift for the shipped templates.

## ADR-011: Control charts downgrade to run charts instead of failing

**Status:** Accepted

**Context:** A control chart (p-chart/u-chart) requested below 12 time
points returned HTTP 400 and a dead end, while most residents' datasets
have four to six points at the time they run the analysis.

**Decision:** The analysis runs a run chart with a median line instead, and
states the reason in the Methods paragraph. `api/analysis_downgrade.py`
aggregates the requested control chart's data the same way the control
chart validator does, so the point count and the downgraded frame cannot
disagree, then substitutes `run_chart` for the executed template, the
generated code, and the persisted `AnalysisRun` row.

**Consequences:** The two `points < 12` errors in `validate_analysis_inputs`
are gone; `run_chart` cannot be requested with fewer than 12 points anymore,
it is produced by substitution instead. `RunChartParams.design_note` carries
the downgrade sentence, which `run_chart.py` prepends to its Methods
paragraph. This does not change ADR-007: `select_template` still uses a
single 12-point threshold, and no second Q6 threshold was added. What
changed is the outcome below that boundary (a working run chart instead of
an error), not the number of thresholds.

## ADR-012: Effect estimates ship with confidence intervals

**Status:** Accepted

**Context:** Every comparison template reported a p-value and a raw
percentage or mean, but no effect estimate with an interval, which is what
a QI poster or abstract needs to convey a magnitude of change, not just
whether it was "significant."

**Decision:** Every comparison reports an effect estimate with a 95%
confidence interval, computed by the shared helpers in
`api/stats_intervals.py`. Before/after proportion reports a risk difference
using Newcombe's hybrid score method rather than the Wald interval, because
QI cell counts are often small and Wald misbehaves near 0 and 100 percent.
Before/after mean reports a pooled-variance t interval on the difference in
means when the t-test runs, matching the equal-variance test actually used,
or a Hodges-Lehmann shift with a Moses order-statistic interval when the
Wilcoxon rank-sum test runs, because it is deterministic and needs no
bootstrap or new dependency. The descriptive summary reports a t-based
interval on each mean and a distribution-free order-statistic interval on
each median.

**Consequences:** `result_summary`, `methods`, and `interpretation` on all
three templates now include the effect size and its interval, which is what
reaches the Results screen, the DOCX/PDF report, and the mentor view with no
`report.py` change. `before_after_pct`'s previously inverted odds ratio in
the chi-square branch was corrected to match `fisher_exact`'s orientation in
the same change.


## ADR-013: Role detection and plan defaults are evidence-based, not size-based

**Context:** A full resident test run with the diabetes clinic dataset showed
that a column was guessed as a denominator because its values were larger than
other integer columns (systolic blood pressure beat every 0/1 flag), which
produced a blocking "numerator exceeds denominator" error between age and a
visit count. The same run showed one chart point per day for a yes/no outcome,
a t-test offered on a yes/no column, and pre and post labels left blank.

**Decision:**

- A denominator is a column whose name reads like one (`api/dataset_profile.py`
  `_DENOM_RE`: total, denom, census, population, visits, patient days, and
  similar). The pairwise size comparison only confirms numerators for such
  columns, and a 0/1 column is never a numerator. `run_data_quality` uses the
  same detector instead of its own.
- A Yes/No outcome column with no stated kind is treated as binary. That gives
  the percentage comparison and the P chart. The P chart needs no denominator,
  and a guessed denominator is not attached to a binary outcome.
- For binary and proportion outcomes the chart period is the finest of day,
  week, month and quarter, no finer than the project's time unit, whose typical
  period holds at least 20 records (`_MIN_RECORDS_PER_PERIOD` in
  `api/plan_builder.py`). The plan states the grouping it chose. The number 20
  is a placeholder pending the clinical owner's answer.
- When the group column has exactly two levels that read like before and after
  (case and padding ignored), those become `pre_val` and `post_val` at medium
  confidence, so the resident still confirms them.
- The "mixed case" warning fires only when one value appears in more than one
  case. The small-group warning and group counts use the case-normalized values.
- `POST /analyze/run-plan/{id}` is serialized by a process-wide lock, because
  it deletes the prior runs and inserts new ones, and two overlapping requests
  each kept a full set.

**Consequences:** Unnamed denominators are no longer guessed, so a resident
whose denominator column has an unusual name assigns it in the Data Review
role table. A per-project lock replaces the process-wide one if runs ever
become slow enough to queue.


## ADR-014: The QI Stat Advisor is optional at every step

**Context:** A provider rate limit made every advisor call fail with the same
"AI service unavailable" text. The resident saw a dead end on the clarification
screen, and the same screen had no way to describe the project by hand while a
key was configured.

**Decision:**

- Residents see one name for the assistant everywhere: "QI Stat Advisor". "AI
  key" stays, because it is the provider key. Every system prompt starts with
  the same identity directive (`IDENTITY_DIRECTIVE` in `api/ai_prompts.py`).
- Provider failures are classified by exception class into `advisor_busy` and
  `advisor_error`, with fixed sentences (ADR-004 still holds: no provider text
  reaches the resident).
- The clarification screen offers "Continue without the QI Stat Advisor" next
  to "Try again", which shows the manual project form, and a way back.
- Plan recommendation already falls back to the rules-first draft when the
  provider fails. Interpretation text is labelled "Draft interpretation" whenever
  the QI Stat Advisor did not write it.
- The Results screen shares one run-and-interpret job per project, upload and
  attempt, so a double effect or double click cannot run the plan twice.

**Consequences:** A resident can finish a project with a dead provider. Draft
text is rule-generated and still carries the bracketed prompts described in the
owner questions.


## ADR-015: Each resident brings their own AI key, and sign-in is throttled

**Context:** The first beta runs from a git clone on each tester's machine and later as one
hosted app. A single app-wide key would let every user spend one person's quota and would
let any account clear everyone's key. The security review also found no sign-in throttling,
a password hash below the current OWASP minimum, mentor comment authors' emails shown to
every link holder (and used as the only check to edit or delete), and uploads read fully into
memory before any size check.

**Decision:**

- The AI key is stored per user (`ai_key_enc:<provider>:<user_id>` in `app_settings`, Fernet
  encrypted). The `.env` key stays as an operator default for a one-person install and is not
  set on a shared host.
- Passwords use PBKDF2-HMAC-SHA256 at 600,000 iterations and old hashes are upgraded on
  sign-in. Failed sign-ins are throttled per account and per IP with in-memory counters.
- Mentor comments carry a per-comment secret issued once to their author. Public views show no
  author email.
- Uploads are read in chunks with a hard stop, zip-based files are checked for expansion, and
  datasets and dictionaries have row, column and page caps.

**Consequences:** In-memory throttle state needs the database or Redis before more than one
worker runs (beta 2, with HTTPS). Comments posted before this change cannot be edited by
their authors because nobody holds a secret for them; the project owner still can.


## ADR-016: Text the app writes follows a plain house style

**Context:** The QI Stat Advisor's replies showed raw Markdown (asterisks around words, numbered
lists run together), em dashes, and stock phrases that make text read as machine-written. The
reports and the mentor page repeat that text, so a resident would paste it into a poster.

**Decision:**

- Every system prompt carries the same style directive (`STYLE_DIRECTIVE` in `api/ai_prompts.py`):
  plain text, no Markdown, no dash punctuation, straight quotes, ordinary words, and a list of
  words and habits to avoid. The list follows the published signs of AI writing (Wikipedia's field
  guide and the humanizer ruleset).
- `api/ai_text.py` enforces it on what comes back, because a model follows an instruction most of
  the time and not every time. It strips Markdown markers, turns dash punctuation into commas,
  periods or "to", straightens quotes, removes emoji and arrows, and replaces a short list of stock
  phrases. It changes form only. Every parsed model reply and every chat reply goes through it.
- `tests/test_house_style.py` fails if a dash, curly quote or stock word appears in the source of
  the app or its interface.

**Consequences:** Replacing a dash with a comma can read slightly less smoothly than a rewrite.
A model reply that needs a real rewrite to lose its machine tone is only caught by the prompt.
