# QI Stat Studio

QI Stat Studio guides medical residents through the statistics of a quality-improvement (QI) project. A resident describes the project in plain language, uploads a CSV or Excel file with a data dictionary, reviews data-quality warnings, runs a recommended analysis, edits the written interpretation, and downloads a Word or PDF report. A mentor can review the work through a share link and leave comments. No statistics training or coding is needed.

## Status: beta

The current release is `1.0.0-beta.2`, a pre-release for testers. The whole workflow runs end to end, but some behavior is still open for decision by the clinical owner, so wording, defaults and statistics choices may change.

- Use synthetic or de-identified data only. The app is not HIPAA compliant.
- It runs on your own machine over plain HTTP. It does not send email.
- Each tester brings their own AI key. Without one the app still works and the QI Stat Advisor stays off.

See [`CHANGELOG.md`](CHANGELOG.md) and [`docs/release-notes/`](docs/release-notes/) for what changed in each release. The version also shows in the page header and at `/health`.

## Who uses it

- A resident runs the project from intake to the final report.
- A mentor opens the share link from the resident's Download screen, reads the work, comments, and approves. The mentor needs no account.

## Requirements

- Python 3.12 or newer
- Node.js 24.15 or newer
- About 1.5 GB of free disk space for the first install

## Install and run

```bash
git clone https://github.com/solomonsjoseph/QI-Stat-Studio.git
cd QI-Stat-Studio
make stub    # first check: offline, no AI key needed
make real    # the real app
```

Both commands set everything up the first time: the Python environment, packages, the language model for name detection, the frontend packages, the database and a `.env` file with its own keys. Later runs skip finished steps and reinstall only when the dependency files changed.

When the servers are ready, `make` opens the app in your browser at `http://127.0.0.1:5173`. On a machine with no display it prints that address instead, and `QISS_NO_BROWSER=1` turns the browser launch off. Press Ctrl+C in the terminal to stop.

Back up the generated `.env`. Uploads cannot be decrypted without its `FERNET_KEY`.

## First use

1. Register. The first account on a copy is its admin.
2. Open Settings, paste your AI key (an OpenRouter key starts with `sk-or-v1-`) and choose Save key. The key belongs to your account only.
3. Describe the project, upload the data file and the data dictionary, and answer the questions.
4. Review the data warnings, accept the plan, run the analysis and edit the text.
5. Download the Word or PDF report.
6. To get a mentor review, copy the share link from the Download screen and send it yourself.

Do not put a shared key in `.env` on a machine several people use. Everyone who signs in to that copy would use it.

## Commands

| Command | What it does |
|---|---|
| `make stub` | Runs the app with an offline AI stub. No key needed. |
| `make real` | Runs the app with the AI settings from `.env` or your Settings key. |
| `make test` | Runs the backend and frontend tests. |
| `make e2e` | Runs the Playwright browser test against running servers. |

The backend uses port 8010 by default. Change it with `make real API_PORT=9000`.

## Troubleshooting

- `No space left on device` during install means the disk or its quota is full. Free space and run `make` again.
- If setup stops partway, run `make real` again. Finished steps are skipped.
- If the QI Stat Advisor says it is unavailable, check that a key is saved in Settings.

## Report a problem

Open an issue with the "Beta bug report" template. Include the version from the page header, the step you were on, and the request ID shown with any error. Do not paste patient data or your AI key.

## Documentation

The full documentation is a Sphinx site with a user guide for residents and mentors and a developer guide for engineers.

```bash
pip install -r docs/requirements.txt
make -C docs html
```

Then open `docs/build/html/index.html`.

## License

For research and educational use within the Rutgers IM Clinic QI program.
