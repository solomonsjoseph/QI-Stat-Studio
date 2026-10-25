# Releasing

Versions follow Semantic Versioning 2.0.0. A beta is a pre-release: `1.0.0-beta.1`, then `1.0.0-beta.2`,
then `1.0.0-rc.1`, then `1.0.0`. Each sorts below the next. Tags have a leading `v`.

To cut a release, after its pull request is merged into `main`:

1. Change the version in `api/version.py`, `web/package.json`, `web/package-lock.json` and `docs/source/conf.py`.
2. In `CHANGELOG.md`, rename `[Unreleased]` to the new version with the date and start a new empty `[Unreleased]`.
3. Write `docs/release-notes/<version>.md` for testers. Keep what users see first, then fixes, then known limitations.
4. Run the backend tests, the frontend tests and `npm run build`.
5. On `main`, create an annotated tag and push it:
   `git tag -a v1.0.0-beta.1 -m "QI Stat Studio 1.0.0-beta.1"` then `git push origin v1.0.0-beta.1`.
6. Create the GitHub release from the tag and mark it as a pre-release while the version has a suffix:
   `gh release create v1.0.0-beta.1 --verify-tag --prerelease --title "1.0.0-beta.1" --notes-file docs/release-notes/1.0.0-beta.1.md`.

`tests/test_version.py` fails if the version strings disagree or the changelog has no entry for the current version.
