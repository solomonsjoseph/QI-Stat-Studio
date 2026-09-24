---
name: run-qi-stat-studio
description: Build, run, and drive QI Stat Studio (FastAPI backend + Vite/React frontend). Use when asked to start the app, run its backend or frontend dev servers, run its Playwright e2e suite, or interact with the running app end to end.
---

QI Stat Studio is a FastAPI backend (`api/`) plus a Vite/React frontend
(`web/`). Drive it via the project's own Playwright e2e suite
(`web/e2e/critical-path.spec.js`), which is the verified harness for
exercising a full resident session (register, login, AI-guided intake,
PHI gate, analysis, report share link) against the two live dev servers.

## Prerequisites

Already satisfied in this environment (Python 3.9.21, Node 24.15.0,
deps and `en_core_web_sm` spaCy model already installed). On a clean
machine, follow the README's `pip install -r requirements.txt` /
`python -m spacy download en_core_web_sm` / `npm install` steps.

## Setup

`.env` already exists with `AI_PROVIDER`, `DB_URL`, and a `FERNET_KEY`.
Migrations are idempotent and safe to re-run:

```bash
alembic upgrade head
```

## Run (agent path)

Start the backend against the deterministic offline AI stub (no network
calls, no API key needed) and the frontend, each in the background:

```bash
# from repo root
AI_PROVIDER=stub nohup uvicorn api.main:app --port 8000 > /tmp/backend.log 2>&1 &
disown

# from web/
nohup npx vite --host 127.0.0.1 > /tmp/frontend.log 2>&1 &
disown
```

Poll until both respond:

```bash
until curl -sf http://127.0.0.1:8000/health -o /dev/null; do sleep 1; done
until curl -sf http://127.0.0.1:5173 -o /dev/null; do sleep 1; done
```

Drive a full resident workflow through a real Chromium instance via the
project's Playwright spec:

```bash
cd web
QISS_E2E=1 npx playwright test e2e/critical-path.spec.js --reporter=list
```

This reuses the two servers started above (it does not spin up its own
backend/frontend — that only happens if `QISS_E2E_START_SERVER=1` is
also set, which uses a separate `e2e_qi_stat_studio.db`). Expected
result: `1 passed` in under 15s.

Logs: `/tmp/backend.log`, `/tmp/frontend.log`. Playwright trace/
screenshots on failure land in `web/test-results/`.

## Run (human path)

```bash
AI_PROVIDER=stub uvicorn api.main:app --reload      # http://localhost:8000, docs at /docs
cd web && npm run dev                               # http://localhost:5173
```

Open `http://localhost:5173`, register (first account becomes admin).
Ctrl-C each process to stop.

## Test

```bash
FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q
cd web && npm run test
```

## Gotchas

- **Vite binds IPv6-only by default.** `npm run dev` / bare `vite` on
  this host listens on `[::1]:5173` only. `curl http://127.0.0.1:5173`
  and Playwright's default `baseURL` (`http://127.0.0.1:5173`) then get
  `ERR_CONNECTION_REFUSED` even though the port "looks" open. Fix: run
  `npx vite --host 127.0.0.1` (or `--host 0.0.0.0`) explicitly.
- **`QISS_E2E=1` is required** to un-skip `critical-path.spec.js` — by
  default the test is skipped with "Set QISS_E2E=1 to run the live
  backend/frontend critical path."
- **spaCy version-mismatch warning is harmless.** `en_core_web_sm`
  (3.8.0) vs installed spacy 3.7.4 prints a `UserWarning` on backend
  startup but does not affect behavior.
- **Backend startup can take 15-30s** the first time (spaCy/thinc model
  load), longer than a naive short poll loop expects — poll `/health`
  rather than assuming it's ready after a few seconds.
