# QI Stat Studio

A guided statistical analysis tool for medical residents conducting quality improvement (QI) projects at Rutgers IM Clinic. Residents answer 9 intake questions, upload a CSV, and receive a publication-ready report — no statistical expertise required.

## Features

- **10-screen wizard** guiding residents from project description to downloadable report
- **6 statistical templates**: descriptive summary, before/after mean, before/after proportion, run chart, p-chart, u/c-chart
- **AI assistance**: pre-fills intake questions from project description; generates plain-language result interpretations
- **PHI protection**: all text is scrubbed (spaCy NER + regex) before any AI call leaves the server
- **Encrypted data**: uploaded CSVs are encrypted at rest with Fernet (AES-128)
- **Report export**: Word (.docx) and PDF with Methods, Results, figure, Limitations, Audit Trail, and R code supplement
- **Mentor sharing**: shareable review link with comment thread; auto-created when Q10 email is provided
- **6 data quality checks** on every upload, with resident acknowledgement before analysis

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy 1.4 + SQLite |
| Statistics | pandas, scipy, pingouin, matplotlib |
| AI proxy | OpenRouter (configurable model) |
| PHI scrubbing | spaCy `en_core_web_sm` + regex |
| Encryption | `cryptography` (Fernet) |
| Reports | python-docx, reportlab |
| Frontend | React 18 + Vite 5 + Tailwind CSS 3 |
| Container | Docker multi-stage (Node build → Python slim) |

## Quick Start (Development)

### Prerequisites

- Python 3.9+
- Node.js 18+
- A Fernet key (generate once; keep secret)

### 1. Generate a Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set:
#   FERNET_KEY=<key from step 1>
#   OPENROUTER_API_KEY=<your OpenRouter key>  # optional; AI features disabled without it
```

### 3. Install and run backend

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm

cd qi_stat_studio   # project root (where api/ lives)
uvicorn api.main:app --reload
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### 4. Install and run frontend

```bash
cd web
npm install
npm run dev
# App available at http://localhost:5173
```

The Vite dev server proxies `/api/*` → `http://localhost:8000/*` (stripping the `/api` prefix to match backend routes).

## Running Tests

```bash
cd qi_stat_studio   # project root
python -m pytest -q
# 57 tests; ~4 seconds
```

## Docker (Production)

```bash
# Build (multi-stage: Node frontend build → Python runtime)
docker build -t qi-stat-studio .

# Run
docker run -p 8000:8000 \
  -e FERNET_KEY=<your-key> \
  -e OPENROUTER_API_KEY=<your-key> \
  qi-stat-studio

# App + API both served at http://localhost:8000
```

## Project Structure

```
qi_stat_studio/
├── api/
│   ├── main.py              # FastAPI app, router registration, static file mount
│   ├── config.py            # Settings (FERNET_KEY, OPENROUTER_API_KEY)
│   ├── database.py          # SQLAlchemy engine + session
│   ├── models_db.py         # ORM models (Project, Upload, AnalysisRun, …)
│   ├── models_api.py        # Pydantic request/response schemas
│   ├── middleware/
│   │   └── phi_scrubber.py  # spaCy NER + regex PHI redaction
│   ├── routers/
│   │   ├── projects.py      # CRUD for projects
│   │   ├── upload.py        # CSV upload, encryption, DQ checks, col-type detection
│   │   ├── analyze.py       # Template selection + /run endpoint
│   │   ├── intake.py        # Save/get intake answers; Q7/Q10 parsing
│   │   ├── share.py         # Mentor share link + comment thread
│   │   ├── ai.py            # /ai/chat — OpenRouter proxy with PHI scrubbing
│   │   ├── report.py        # /report/{id}/docx and /pdf
│   │   └── settings_router.py
│   └── templates/
│       ├── registry.py      # TEMPLATE_REGISTRY dict
│       ├── descriptive.py
│       ├── before_after_mean.py
│       ├── before_after_pct.py
│       ├── run_chart.py
│       ├── p_chart.py
│       ├── u_c_chart.py
│       └── codegen.py       # R code generation for all 6 templates
├── web/
│   ├── src/
│   │   ├── App.jsx          # Context router; /mentor/<token> URL detection
│   │   ├── api.js           # Typed fetch wrapper for all endpoints
│   │   └── screens/         # 12 screen components
│   ├── vite.config.js       # /api proxy with prefix-strip rewrite
│   └── package.json
├── tests/                   # 57 pytest tests
├── Dockerfile               # Multi-stage build
├── requirements.txt
└── .env.example
```

## API Reference

All endpoints are documented at `http://localhost:8000/docs` (Swagger UI) when the server is running.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects` | Create project |
| GET | `/projects` | List projects |
| POST | `/upload/{project_id}` | Upload + encrypt CSV |
| PUT | `/upload/{upload_id}/column-types` | Confirm column types |
| POST | `/intake/{project_id}` | Save intake answers |
| GET | `/intake/{project_id}` | Get answers + intervention_date |
| POST | `/analyze/run` | Run statistical template |
| POST | `/ai/chat` | PHI-scrubbed AI chat (OpenRouter) |
| GET | `/report/{run_id}/docx` | Download Word report |
| GET | `/report/{run_id}/pdf` | Download PDF report |
| POST | `/share/{project_id}/create` | Create mentor share link |
| GET | `/share/view/{token}` | Mentor view |
| POST | `/share/view/{token}/comment` | Add mentor comment |
| GET | `/settings` | Get all app settings |
| PUT | `/settings` | Upsert a setting key/value |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FERNET_KEY` | **Yes** | Base64 Fernet key for at-rest CSV encryption. App refuses to start without it. |
| `OPENROUTER_API_KEY` | No | Enables AI features (intake pre-fill, result interpretation). AI endpoints return 503 without it. |
| `OPENROUTER_MODEL` | No | Default: `anthropic/claude-sonnet-4-6` |

## License

For research and educational use within the Rutgers IM Clinic QI program.
