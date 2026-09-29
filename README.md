# QI Stat Studio

QI Stat Studio is a guided statistical analysis app for medical residents
running quality-improvement (QI) projects. A resident describes a project,
uploads a CSV or Excel file, confirms data-quality checks, runs one of six
guide-recommended analyses, edits the interpretation, and downloads a
Word/PDF report or shares an in-browser mentor review link. No statistics
training or coding required.

Full documentation (user guide, architecture, API reference, data model,
security design, testing, and deployment) lives in [`docs/`](docs/) and is
built with Sphinx. See **Documentation** below to build and browse it.

## Quick start

**Prerequisites:** Python 3.10+ (3.11 recommended), Node.js 20.19+ (or 22.12+, per Vite 8's `engines` requirement).

```bash
pip install -r requirements.txt && python -m spacy download en_core_web_sm
cd web && npm install && cd ..
cp .env.example .env   # set FERNET_KEY; for real AI also set the provider key
make stub              # or: make real
```

Open `http://127.0.0.1:5173` and register. First account becomes admin.

## Commands

| Command | Description |
|---|---|
| `make stub` | Backend + frontend with offline AI stub (no API key). |
| `make real` | Backend + frontend using `AI_PROVIDER` / keys from `.env`. |
| `make test` | Backend pytest + frontend vitest. |
| `make e2e` | Playwright critical path (servers already running). |
| `alembic upgrade head` | Apply database migrations (also run by `make stub`/`real`). |
| `docker build -t qi-stat-studio . && docker run -p 8000:8000 ...` | Build and run the production container. |

## Documentation

```bash
pip install -r docs/requirements.txt
make -C docs html
```

Then open `docs/build/html/index.html` in a browser. The site has two
independent guides:

- **User Guide**: for residents and mentors. The full walkthrough, task
  how-tos, exact intake question wording, and the six analyses explained in
  plain English.
- **Developer Guide**: for engineers. Local setup, system architecture, the
  full data model, complete API reference, security/PHI design, the test
  suite, and deployment.

## License

For research and educational use within the Rutgers IM Clinic QI program.
