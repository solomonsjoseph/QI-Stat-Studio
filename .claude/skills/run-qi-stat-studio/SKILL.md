---
name: run-qi-stat-studio
description: Build, run, and drive QI Stat Studio (FastAPI backend + Vite/React frontend). Use when asked to start the app, run its backend or frontend dev servers, run its Playwright e2e suite, or interact with the running app end to end.
---

QI Stat Studio = FastAPI (`api/`) + Vite/React (`web/`). One command starts both.

## Run

```bash
make stub   # test: offline AI stub, no API key
make real   # real: uses AI_PROVIDER + keys from .env
```

Open http://127.0.0.1:5173 (API docs http://127.0.0.1:8000/docs). Ctrl-C stops both.

`.env` must exist (`FERNET_KEY`, `DB_URL`; for `real`, also the provider key). Migrations run automatically.

## Agent path (background)

```bash
AI_PROVIDER=stub nohup uvicorn api.main:app --port 8000 > /tmp/backend.log 2>&1 & disown
nohup npx --prefix web vite --host 127.0.0.1 --port 5173 > /tmp/frontend.log 2>&1 & disown
until curl -sf http://127.0.0.1:8000/health >/dev/null; do sleep 1; done
until curl -sf http://127.0.0.1:5173 >/dev/null; do sleep 1; done
```

Drive the app: `make e2e` (expects servers already up; `1 passed` in ~15s). Logs: `/tmp/backend.log`, `/tmp/frontend.log`.

## Test

```bash
make test   # pytest + vitest
make e2e    # Playwright critical path (servers must be running)
```

## Gotchas

- Prefer `make stub` / `npx vite --host 127.0.0.1` — bare Vite may bind `[::1]` only and break `127.0.0.1:5173`.
- `QISS_E2E=1` is required or the critical-path spec skips.
- First backend start can take 15–30s (spaCy load); poll `/health`.
- spaCy 3.8 model vs 3.7.4 warning is harmless.
- Clean machine: `pip install -r requirements.txt && python -m spacy download en_core_web_sm && cd web && npm install`.
