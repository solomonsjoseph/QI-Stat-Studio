# Contributing

This repository follows the
[repo standard](https://github.com/solomonsjoseph/repo-standard/blob/main/STANDARD.md).
The short version:

1. Open an issue for any feature or bug. Chores and docs may skip it.
2. Branch from `main`: `<type>/<issue>-<slug>`, for example `feat/12-csv-export`.
3. Install the hooks once per clone:

   ```bash
   pre-commit install --hook-type pre-commit --hook-type commit-msg
   ```

4. Commit with Conventional Commits: `type(scope): subject`, imperative and
   lowercase, with a body that explains why. Types: `feat`, `fix`, `perf`, `refactor`,
   `docs`, `test`, `build`, `ci`, `chore`, `revert`.
5. Open a pull request with the same title format and fill in every section
   of the template. Keep it small, around 100 changed lines.
6. The `ci` and `pr-title` checks must pass and every review conversation must
   be resolved. Pull requests are squash-merged.
7. Releases are automatic: release-please opens a release PR from the commits
   on `main`, and merging it publishes the version.

Source files are English and plain ASCII only.
