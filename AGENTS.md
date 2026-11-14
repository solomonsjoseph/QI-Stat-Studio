# Agent instructions

Coding agents working in this repository follow the
[repo standard](https://github.com/solomonsjoseph/repo-standard/blob/main/STANDARD.md):

- Never push to `main`. Work on `<type>/<issue>-<slug>` branches and land
  changes through squash-merged pull requests.
- Commit messages and PR titles use Conventional Commits: `type(scope): subject`.
- Fill in every section of the PR template. Run a code review on the diff and
  address the findings before merging.
- Keep `ci` and `pr-title` green. Never weaken a check to make it pass.
- Source files are English and plain ASCII only. No secrets or real personal data.
- `CHANGELOG.md` is written by hand. release-please bumps the versions, tags and
  writes the GitHub release, but skips the changelog; add the new version's
  `## [X.Y.Z]` entry on the release PR branch before merging it
  (tests/test_version.py checks it).

## Project notes

- `make stub` runs the app offline; `make real` runs it with AI settings.
- `make test` runs the backend tests (pytest) and the frontend tests (vitest).
- Python dependencies are pinned in `requirements.txt` and `requirements-dev.txt`
  (pip); the frontend lives in `web/` (npm).
- The version string lives in `api/version.py`, `web/package.json` and
  `docs/source/conf.py`; release-please bumps all three.
- Test data is synthetic. Never commit real or patient data, uploads,
  databases or `.env`.
