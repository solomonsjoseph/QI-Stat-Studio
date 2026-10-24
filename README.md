# QI Stat Studio

QI Stat Studio is a guided statistical analysis app for medical residents
running quality-improvement (QI) projects. A resident describes a project,
uploads a CSV or Excel file, confirms data-quality checks, runs one of seven
guide-recommended analyses, edits the interpretation, and downloads a
Word/PDF report or shares an in-browser mentor review link. No statistics
training or coding required.

Full documentation (user guide, architecture, API reference, data model,
security design, testing, and deployment) lives in [`docs/`](docs/) and is
built with Sphinx. See **Documentation** below to build and browse it.

## Beta quick start (git clone)

Current release: 1.0.0-beta.1 (a pre-release). See [`CHANGELOG.md`](CHANGELOG.md) and
[`docs/release-notes/`](docs/release-notes/). The version also shows in the page header and at `/health`.

Each tester runs their own copy and brings their own AI key.

1. Install Python 3.9+ and Node.js 20.19+ (see below), then `git clone <repo-url> && cd qi_stat_studio`.
2. `make real`. The first run builds everything and creates `.env` with its own `FERNET_KEY`
   and `SECRET_KEY`. Back up `.env`: uploads cannot be decrypted without the `FERNET_KEY`.
3. Open `http://127.0.0.1:5173` and register. The first account on a copy is its admin.
4. Open **Settings**, paste your own AI key (an OpenRouter key looks like `sk-or-v1-...`) and
   click **Save key**. The key belongs to your account only. Without a key the app still
   works, and the QI Stat Advisor stays off.
5. Use synthetic or de-identified data only. This prototype is not HIPAA compliant.

Do not put a shared key in `.env` on a machine several people use: an `.env` key is used by
everyone who signs in to that copy. A key saved in Settings is used only by its owner.

## Quick start

**Prerequisites:** Python 3.9+ (3.11 recommended; 3.9 needs `eval_type_backport`, which requirements.txt installs), Node.js 20.19+ (or 22.12+, per Vite 8's `engines` requirement).

```bash
git clone <repo-url> && cd qi_stat_studio
make stub   # offline AI stub, no key needed. Or: make real (set your AI key in .env first)
```

The first run creates `.venv`, installs Python and npm dependencies, downloads
the spaCy model, creates a git-ignored `.env` with a generated `FERNET_KEY`, and
applies migrations. Later runs skip finished steps. Back up `FERNET_KEY`:
uploads cannot be decrypted without it.

Open `http://127.0.0.1:5173` and register. First account becomes admin.

The backend listens on `API_PORT` (default 8010; for example `make stub API_PORT=9000`).

## QI Stat Advisor

On Data Review the QI Stat Advisor explains each data warning and proposes
fixes. You select warnings, then acknowledge them or clarify them with the
advisor. Nothing changes until you confirm, and agreed changes are listed in a
handoff document and applied to your data before any analysis. The advisor
needs an AI key: put it in `.env` (`make real`) or paste it on the Settings
screen, where a saved key overrides `.env`. Without a key the app still works
manually.

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
  how-tos, exact intake question wording, and the seven analyses explained in
  plain English.
- **Developer Guide**: for engineers. Local setup, system architecture, the
  full data model, complete API reference, security/PHI design, the test
  suite, and deployment.

## License

For research and educational use within the Rutgers IM Clinic QI program.
