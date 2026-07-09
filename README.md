# QI Stat Studio

QI Stat Studio is a guided statistical analysis app for medical residents
running quality-improvement (QI) projects. A resident describes a project,
uploads a CSV or Excel file, confirms data-quality checks, runs one of six
guide-recommended analyses, edits the interpretation, and downloads a
Word/PDF report or shares an in-browser mentor review link — no statistics
training or coding required.

Full documentation — user guide, architecture, API reference, data model,
security design, testing, and deployment — lives in [`docs/`](docs/) and is
built with Sphinx. See **Documentation** below to build and browse it.

## Quick start

**Prerequisites:** Python 3.10+ (3.11 recommended), Node.js 18+.

```bash
# 1. Install backend dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 2. Configure the environment
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste the generated key into .env as FERNET_KEY

# 3. Create the database schema
alembic upgrade head

# 4. Run the backend
uvicorn api.main:app --reload
```

In a second shell:

```bash
# 5. Run the frontend
cd web
npm install
npm run dev
```

Open `http://localhost:5173` and register an account — the first user ever
registered becomes admin, everyone after that is a resident.

## Commands

| Command | Description |
|---|---|
| `uvicorn api.main:app --reload` | Run the backend (`http://localhost:8000`, API docs at `/docs`). |
| `cd web && npm run dev` | Run the frontend dev server (`http://localhost:5173`). |
| `alembic upgrade head` | Apply database migrations. |
| `FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q` | Run backend tests. |
| `cd web && npm run test` | Run frontend unit tests. |
| `cd web && npm run e2e` | Run Playwright end-to-end tests. |
| `docker build -t qi-stat-studio . && docker run -p 8000:8000 ...` | Build and run the production container. |

## Documentation

```bash
pip install -r docs/requirements.txt
make -C docs html
```

Then open `docs/build/html/index.html` in a browser. The site has two
independent guides:

- **User Guide** — for residents and mentors: the full walkthrough, task
  how-tos, exact intake question wording, and the six analyses explained in
  plain English.
- **Developer Guide** — for engineers: local setup, system architecture,
  the full data model, complete API reference, security/PHI design,
  the test suite, and deployment.

## License

For research and educational use within the Rutgers IM Clinic QI program.
