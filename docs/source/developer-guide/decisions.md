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
tests — see {doc}`data-model`).

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

## ADR-005: Mentor shares are view-only — downloads were built, then removed

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
endpoint at runtime (admin-editable without a restart — see {doc}`how-to`).

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
drift for the six shipped templates.
