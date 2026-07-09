# How-to guides

Task-focused steps for residents and mentors who already know the app. If
you want the full walkthrough instead, see the {doc}`tutorial`.

## Resume a project you started earlier

From the landing page, find the project under **Resume Existing Project**
and click it (or **Resume**). The app takes you back to exactly the screen
you left off on. It re-derives your position from what's actually saved
(your latest intake answers, upload, analysis run, and any edits), so
closing the tab mid-workflow never leaves you at the wrong step.

## Fix a data-quality ERROR

When Data Review shows a red **ERROR** (for example, duplicate patient IDs),
you cannot check a box past it — the file itself must change. Click
**Re-upload corrected file**, fix the underlying spreadsheet, and upload it
again from the Upload screen.

## Re-upload a corrected file after a warning-only review

If you already acknowledged warnings but realize the data was wrong, go back
to the Upload screen (using the wizard's back button) and upload the
corrected file. The new upload replaces the old one for this project; run
the analysis again afterward so the report reflects the corrected data.

## Change which columns feed an analysis

If you picked the wrong columns on **Map Your Columns**, use the wizard's
back button to return to that screen, change the dropdowns, and click
**Run Analysis** again. Re-running clears the previous results and
interpretation, so the report can't end up mixing data from two different
runs.

## Share with a second mentor

Go to **Download & Share** and click **Share with mentor** again. If the
mentor's email is different from your Q10 answer, a new share link is
created for that mentor. If it's the same, the app reuses the existing
active link instead of creating duplicates.

## Revoke or regenerate a mentor link

Mentor links expire automatically after 30 days, but you don't have to
wait. Revoking immediately invalidates a link (the mentor gets a
"not found" page); regenerating revokes the old link and issues a
brand-new one, which is useful if a link was sent to the wrong address.
Both actions are available from the project's share management; ask your
admin if you don't see them exposed in your build, since some deployments
manage this through the API directly (`POST /share/{project_id}/revoke` /
`POST /share/{project_id}/regenerate` via the API docs at `/docs`).

## Read and reply to mentor comments

Mentor comments appear inline with the shared report on the mentor's review
page. As the resident, you'll see the same comments in your project once the
mentor posts them. Mentors can edit or delete their own comments, but they
need to re-enter the email they originally commented with — that's what
proves it's the same mentor, since mentors never create an account.

## Update your report before re-downloading

Go back to **Edit & Review**, change the title, caption, or interpretation,
and click **Save & Continue**. Every prior version of an edited field stays
in the report's Audit Trail instead of being overwritten, so a mentor or
program director can see exactly what you changed and when.

## Archive a project you're done with

From the landing page, click **Archive** next to a project. Archived
projects drop out of your default project list but aren't deleted; ask your
admin if you need a project permanently removed.

## Admin: manage runtime settings

Admins see a **Settings** link that residents don't. It lists the current
values for things like the clinic name shown in reports, which AI
provider/model is active, and the AI rate limit, and lets you add or update
one setting at a time. Secrets (API keys, the database URL, the encryption
key) are never editable here — they live only in the server's environment
configuration; see {doc}`../developer-guide/how-to` if you're the one
managing that deployment.

## Admin: review failed analyses and send deadline reminders

Two admin-only capabilities are exposed through the API rather than a
dedicated screen, reachable at `/docs` (Swagger UI) while signed in as
admin:

- `GET /admin/failures` — a searchable log of failed analyses/uploads/AI
  calls, with enough context to help a resident (request ID, project, route)
  without exposing raw patient data.
- `POST /notifications/deadline-reminders/run` — sends a reminder email to
  any mentor whose share has a deadline within the next 7 days and who
  hasn't already been reminded. Run this periodically (e.g. from a scheduled
  job) if your deployment wants automatic reminders.
