# QI Stat Studio

QI Stat Studio is a guided statistical analysis app for medical residents running quality-improvement (QI) projects. It helps a resident describe a project, upload CSV or Excel data, confirm data quality checks, run one of six appropriate analyses, edit the interpretation, download Word/PDF reports, and share an in-browser mentor review link.

## Features

- **10-screen wizard**: landing → description → intake → upload → review → analysis → parameters → results → edit → download.
- **Six statistical analyses**: descriptive summary, before/after average, before/after percentage, run chart, p-chart, and u/c-chart.
- **Guide-based recommendations**: the app ranks three analysis options and marks the recommended choice.
- **AI assistance**: intake pre-fill from the project description and plain-language result interpretation.
- **AI provider options**: OpenRouter / OpenAI / local (Ollama) via LiteLLM.
- **PHI protection**: text is scrubbed with spaCy NER plus regex before every AI call leaves the server.
- **Encrypted uploads**: CSV/Excel files are encrypted at rest with Fernet.
- **Data quality checks**: warnings require resident acknowledgement; blocking errors require a corrected re-upload.
- **Report export**: Word and PDF reports include methods, results, figures, interpretation, limitations, audit trail, and selected R/SPSS/SAS code supplements.
- **Mentor review**: residents can create expiring/revocable share links; mentors can view the report package in the browser and comment, but cannot download or modify reports.
- **Deadline reminders**: admins can trigger reminder-email sweeps for mentor/share deadlines.

## What a resident does

1. Log in or register. The first registered user becomes the admin; later users are residents.
2. Create or resume a QI project.
3. Tell the app about the project in one or two sentences.
4. Answer short intake questions. "I'm not sure" is always allowed when the resident does not know an answer.
5. Upload a CSV or Excel file.
6. Review the first five rows, confirm detected column types, and acknowledge any data-quality warnings.
7. Pick the recommended analysis, or choose one of the other ranked options.
8. Confirm the analysis parameters and run the analysis.
9. Review the figure/table and edit the title, caption, or interpretation.
10. Download Word/PDF reports and share an in-browser mentor review link.

## The six analyses, in plain English

| Analysis | Use it when | What the tool does |
|----------|-------------|--------------------|
| Descriptive summary | You need a Table 1 or one-period summary. | Summarizes counts, averages, medians, and missingness, optionally by group. |
| Before/after average | You compare an average or median before vs. after. | Decides between a t-test and Wilcoxon test from assumption checks. |
| Before/after percentage | You compare a proportion before vs. after. | Decides between chi-square and Fisher's exact test from expected cell counts. |
| Run chart | You track a value over time, usually with fewer time points. | Plots time units, a median line, intervention marker, and run-chart signal checks. |
| p-chart | You track a percentage/proportion over time. | Computes weighted 3-sigma control limits from the numerator and denominator. |
| u/c-chart | You track rates or counts over time. | Uses a u-chart when denominators vary and a c-chart when counts or stable denominators apply. |

The app runs the statistics itself. R/SPSS/SAS code supplements are export-only documentation that reproduce the completed analysis; residents do not need to run code.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, SQLAlchemy 2.0, SQLite, Alembic, Pydantic Settings |
| Statistics | pandas, scipy, pingouin, matplotlib |
| AI proxy | OpenRouter / OpenAI / local Ollama via LiteLLM |
| PHI scrubbing | spaCy `en_core_web_sm` plus regex redaction |
| Encryption | `cryptography` Fernet |
| Reports | python-docx, reportlab |
| Frontend | React 18, Vite 8, Tailwind CSS 3 |
| Container | Docker multi-stage build: Node frontend build → Python 3.11 slim runtime |

## Quick Start (Development)

### Prerequisites

- Python 3.10+; Python 3.11 is recommended and used by Docker.
- Node.js 18+.
- A Fernet key for upload encryption.

### 1. Install backend dependencies

From the `qi_stat_studio/` directory:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 2. Configure environment

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Edit `.env` and set `FERNET_KEY` to the generated value. The example file includes all supported variables: AI provider settings, database URL aliases, session secret, SMTP, and sender email.

### 3. Create the database schema

The app does not auto-create tables during normal development startup. Run Alembic before uvicorn:

```bash
alembic upgrade head
```

### 4. Run the backend

```bash
uvicorn api.main:app --reload
```

- API: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- Readiness check: `http://localhost:8000/readyz`

### 5. Run the frontend

In another shell:

```bash
cd web
npm install
npm run dev
```

The app runs at `http://localhost:5173`. The Vite dev server proxies `/api/*` to the FastAPI backend and strips the `/api` prefix.

### 6. Register the first user

Open the frontend and register an email/password account. The first registered user becomes `admin`; Settings and admin endpoints require this admin user. Later registrations become resident users.

## Running Tests

Backend:

```bash
cd qi_stat_studio
FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q
```

Frontend unit/component tests:

```bash
cd qi_stat_studio/web
npm run test
```

Frontend end-to-end tests:

```bash
cd qi_stat_studio/web
npm run e2e
```

## Docker

```bash
cd qi_stat_studio
docker build -t qi-stat-studio .
docker run -p 8000:8000 \
  -e FERNET_KEY=<your-fernet-key> \
  -e SECRET_KEY=<production-session-secret> \
  -e AI_PROVIDER=openrouter \
  -e OPENROUTER_API_KEY=<optional-openrouter-key> \
  qi-stat-studio
```

The Docker entrypoint runs `alembic upgrade head` before starting uvicorn. The built frontend and API are both served from `http://localhost:8000`.

## Project Structure

```text
qi_stat_studio/
├── api/
│   ├── main.py              # FastAPI app, middleware, error handling, static frontend mount
│   ├── config.py            # Settings and FERNET_KEY enforcement
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models_db.py         # ORM models
│   ├── models_api.py        # Pydantic request/response schemas
│   ├── routers/             # Auth, projects, upload, intake, analyze, AI, reports, share, settings, health
│   ├── templates/           # Six analysis templates and code generation
│   ├── middleware/          # PHI scrubber
│   └── services/            # Notifications and provider utilities
├── alembic/                 # Database migrations
├── tests/                   # Backend pytest suite
├── web/
│   ├── src/App.jsx          # Wizard context/router
│   ├── src/api.js           # Frontend API wrapper
│   ├── src/screens/         # Screen components
│   ├── package.json         # Vite/Vitest/Playwright scripts
│   └── vite.config.js       # Dev proxy
├── Dockerfile
├── requirements.txt
└── .env.example
```

## API Reference

All endpoints are available in Swagger UI at `/docs` when the backend is running.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register user; first user becomes admin. |
| POST | `/auth/login` | Log in and set the session cookie. |
| POST | `/auth/logout` | Revoke the current session. |
| GET | `/auth/me` | Return current user. |
| POST | `/projects` | Create project. |
| GET | `/projects` | List current user's projects. |
| GET | `/projects/{project_id}/resume` | Resume project with latest upload/run/share context. |
| PATCH | `/projects/{project_id}` | Update project title, description, deadline, or status. |
| DELETE | `/projects/{project_id}` | Archive/delete project. |
| POST | `/intake/{project_id}` | Save intake answers. |
| GET | `/intake/{project_id}` | Get saved answers plus parsed intervention date. |
| POST | `/upload/{project_id}` | Upload, encrypt, scan, summarize, and preview CSV/Excel data. |
| GET | `/upload/project/{project_id}` | List active uploads for a project. |
| GET | `/upload/{upload_id}` | Get upload metadata. |
| DELETE | `/upload/{upload_id}` | Mark upload deleted and remove encrypted bytes. |
| POST | `/upload/{project_id}/replace/{upload_id}` | Replace an active upload. |
| PUT | `/upload/{upload_id}/column-types` | Confirm column types and column map. |
| PATCH | `/upload/{upload_id}/acknowledged-flags` | Save acknowledged data-quality warnings. |
| GET | `/analyze/{project_id}/recommend` | Return three ranked analysis recommendations. |
| POST | `/analyze/run` | Validate parameters and run a statistical template. |
| POST | `/ai/intake-prefill` | PHI-scrubbed AI prefill for Q2-Q7. |
| POST | `/ai/chat` | PHI-scrubbed AI interpretation/chat endpoint. |
| GET | `/report/{run_id}/docx` | Authenticated resident Word report download. |
| GET | `/report/{run_id}/pdf` | Authenticated resident PDF report download. |
| POST | `/share/{project_id}/create` | Create or reuse mentor share link and optionally email it. |
| POST | `/share/{project_id}/revoke` | Revoke a mentor share link. |
| POST | `/share/{project_id}/regenerate` | Revoke and regenerate a mentor share link. |
| GET | `/share/view/{token}` | Public mentor browser view; no report downloads. |
| POST | `/share/view/{token}/comment` | Add mentor comment. |
| PATCH | `/share/view/{token}/comment/{comment_id}` | Edit mentor's own public comment. |
| DELETE | `/share/view/{token}/comment/{comment_id}` | Delete mentor's own public comment. |
| PATCH | `/share/{project_id}/comment/{comment_id}` | Resident/owner edit of mentor comment. |
| DELETE | `/share/{project_id}/comment/{comment_id}` | Resident/owner delete of mentor comment. |
| GET | `/settings` | Admin settings list. |
| PUT | `/settings` | Admin setting upsert. |
| GET | `/health` | Public liveness check. |
| GET | `/readyz` | Readiness check for database and Fernet configuration. |
| GET | `/admin/failures` | Admin failure-log search/filter endpoint. |
| POST | `/notifications/deadline-reminders/run` | Admin-triggered reminder sweep; run periodically, e.g. cron. |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FERNET_KEY` | Yes | Base64 Fernet key. The app raises `RuntimeError` on startup when missing. Upload encryption and reading encrypted files require it. |
| `SECRET_KEY` | Production | Session signing/secret material. The default dev value is rejected in production. |
| `DB_URL` / `DATABASE_URL` / `db_url` | Optional | SQLAlchemy database URL. Defaults to `sqlite:///./qi_stat_studio.db`; `DB_URL` and `DATABASE_URL` are accepted aliases. |
| `AI_PROVIDER` | Optional | `openrouter`, `openai`, or `local`; defaults to `openrouter`. |
| `OPENROUTER_API_KEY` | Optional | Enables OpenRouter AI calls. Without provider credentials, AI endpoints return unavailable responses but core analysis still works. |
| `OPENROUTER_MODEL` | Optional | OpenRouter model name. |
| `OPENAI_API_KEY` | Optional | Enables OpenAI when `AI_PROVIDER=openai`. |
| `OPENAI_MODEL` | Optional | OpenAI model name. |
| `LOCAL_API_BASE` | Optional | Local OpenAI-compatible/Ollama base URL when `AI_PROVIDER=local`. |
| `LOCAL_API_KEY` | Optional | Local provider API key if required by the local gateway. |
| `LOCAL_MODEL` | Optional | Local model name. |
| `SMTP_HOST` / `SMTP_PORT` | Optional | SMTP server for mentor invites and deadline reminders. Without SMTP credentials, email sending fails but share links still exist. |
| `SMTP_USER` / `SMTP_PASS` | Optional | SMTP credentials. |
| `FROM_EMAIL` | Optional | Sender address for notification emails. |
| `COOKIE_SECURE` | Optional | Set secure cookies in HTTPS production deployments. |
| `CORS_ORIGINS` | Optional | Comma-separated or JSON-list origins for browser clients. |
| `ENVIRONMENT` | Optional | Use `production` to enforce production-only safety checks. |

## Security Notes

- PHI scrubbing runs before every AI call. The resident sees a banner when intake text was de-identified before AI prefill.
- CSV/Excel rows are never sent to the AI by the frontend. AI interpretation uses summaries and selected analysis metadata, not raw row-level data.
- Uploaded files are encrypted at rest with Fernet and stored outside the database.
- Mentor links expose an in-browser review package and comments only; mentors cannot download DOCX/PDF reports or modify resident content.
- Do not commit `.env`, database files, encrypted uploads, or production secrets.

## License

For research and educational use within the Rutgers IM Clinic QI program.
