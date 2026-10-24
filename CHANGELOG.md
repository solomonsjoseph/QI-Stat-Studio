# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning 2.0.0](https://semver.org/). A beta is a pre-release, so `1.0.0-beta.1` sorts
before `1.0.0`.

## [Unreleased]

Changes the clinical owner asks for after beta 1 go here.

## [1.0.0-beta.1] - 2026-10-24

First beta. It runs from a git clone on each tester's own machine. Hosting and HTTPS are planned for beta 2.

### Added

- A guided seven-step flow for a resident: project intake, clarification, data review, analysis plan, results, edits, and Word and PDF reports.
- The QI Stat Advisor, which is optional. It reads data warnings, proposes fixes the resident can edit before they apply, and drafts interpretations. With no AI key every step still works through rules.
- Batch review of data-quality warnings, with acknowledge and clarify choices and a handoff document.
- A rules-first analysis plan, so the plan exists before any AI is asked.
- Per-user AI keys, stored encrypted and used only by their owner.
- A mentor review link that needs no account. A mentor can comment, edit and delete their own comments, and sign off with a comment. Mentor comments appear in the Word and PDF reports.
- Sign-in throttling, generic sign-in errors and an audit log of sign-in failures.
- Upload limits on size, rows, columns, PDF pages and zip expansion.
- The release version in the page header and in `/health`.

### Changed

- The report title is centered in the Word and PDF reports.
- PDF tables wrap their text and fit the page, and headings stay with the content that follows them.
- Data review shows the real missing-value percentage and no longer reports a false "numerator exceeds denominator" error.
- A denominator column is used only when it is recognised as one. This applies to columns the QI Stat Advisor names too.
- Mixed-case group labels such as `Pre` and `pre` are treated as one group.
- The advisor is named "QI Stat Advisor" everywhere. "AI key" still names the provider key.

### Fixed

- Errors no longer pass silently. Failed advisor calls, unreadable advisor answers, unreadable plans and figures that cannot be placed now say what failed and log the error class.
- Leading zeros in identifier columns are kept on upload.
- Control charts no longer plot a blank count or a calendar gap as a measured zero.
- Phone numbers in parentheses and two-digit-year dates are redacted before any AI call.

### Security

- Passwords use PBKDF2-HMAC-SHA256 with 600,000 iterations.
- A mentor comment can be edited only by its author. Other link holders never see an email address.
- Uploads are encrypted at rest. Patient identifiers are scrubbed before any AI call leaves the server.

### Known limitations

- Sharing with a mentor does not send email, because no mail server is configured. The resident copies the link.
- Not HIPAA compliant. Use synthetic or de-identified data only.
- The app runs over plain HTTP on the tester's own machine. HTTPS comes with hosting in beta 2.
- Several clinical decisions are still open with the clinical owner. They are listed in the owner questions file.

[Unreleased]: https://github.com/solomonsjoseph/QI-Stat-Studio/compare/v1.0.0-beta.1...HEAD
[1.0.0-beta.1]: https://github.com/solomonsjoseph/QI-Stat-Studio/releases/tag/v1.0.0-beta.1
