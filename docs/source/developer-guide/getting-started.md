# Getting started

Get the app running locally, end to end: backend, frontend, database, and
your first user account.

## Prerequisites

- Python 3.10+ (3.11 is what Docker uses in production; prefer it locally
  too).
- Node.js 18+.
- A Fernet key for upload encryption, generated below. There's no default;
  the app refuses to start without one.

## 1. Install backend dependencies

From the repository root:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

`en_core_web_sm` is spaCy's small English NER model, used by the PHI
scrubber (see {doc}`security`) to catch names/dates/orgs that regex alone
would miss. If it's missing, the scrubber logs a warning and falls back to
regex-only redaction instead of crashing the app.

## 2. Configure the environment

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the generated value into `.env` as `FERNET_KEY`. `.env.example`
documents every other variable (AI provider, database URL, session secret,
SMTP); see {doc}`how-to` for what each one does and when you need it.

## 3. Create the database schema

The app does **not** auto-create tables on a normal `uvicorn` startup; that's
Alembic's job:

```bash
alembic upgrade head
```

This runs the full migration chain (5 revisions — see {doc}`data-model`)
against whatever `DB_URL`/`DATABASE_URL` resolves to; the default is
`sqlite:///./qi_stat_studio.db`.

## 4. Run the backend

```bash
uvicorn api.main:app --reload
```

- API: `http://localhost:8000`
- Interactive API docs (Swagger UI): `http://localhost:8000/docs`
- Liveness: `GET /health` — always `{"status": "ok"}`, no auth, no DB check.
- Readiness: `GET /readyz` — checks the database connection and that
  `FERNET_KEY` actually decodes; returns HTTP 503 with a per-check breakdown
  if either fails.

## 5. Run the frontend

In a second shell:

```bash
cd web
npm install
npm run dev
```

The app is now at `http://localhost:5173`. Vite's dev server proxies
`/api/*` to `http://localhost:8000` and strips the `/api` prefix (see
`web/vite.config.js`). In production the same `api.js` client instead talks
to the FastAPI app directly, which is why `api/main.py` also has an
`ApiPrefixMiddleware` that strips `/api` server-side (see
{doc}`architecture`).

## 6. Register your first user

Open `http://localhost:5173` and register an email/password account. **The
very first user ever registered on a given database becomes `admin`**;
every registration after that becomes a `resident`. There's no separate
admin-invite flow. If you need a second admin, promote them directly in the
database; there's no API endpoint for it, by design, since admin escalation
isn't something the app exposes over HTTP.

## 7. Confirm it all works

Run the backend test suite (it uses its own throwaway SQLite file, never
your dev database):

```bash
FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q
```

See {doc}`testing` for what each of the ~29 backend test files covers, the
frontend unit/E2E commands, and why that specific dummy Fernet key value is
the project convention.
