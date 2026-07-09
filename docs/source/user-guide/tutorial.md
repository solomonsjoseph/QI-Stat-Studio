# Tutorial: your first QI project

This walks through one complete project, start to finish: a resident tracking
monthly wait times before and after a scheduling change. By the end you'll
have a downloaded Word/PDF report and a mentor review link.

You need: a web browser, and a CSV or Excel export of your QI data (or the
sample dataset your admin may have provided).

## 1. Sign in

Open the app in your browser. The first person to ever register on a given
deployment becomes the **admin**; everyone who registers after that is a
**resident**. If this is a brand-new deployment and you're the first person
in, you're the admin. You can still create and run projects normally, and
you also get access to {doc}`Settings and admin tools <how-to>`.

Click **Register**, enter your email and a password, and click **Create
Account**. Next time, use **Login**.

## 2. Start a project

On the landing page, click **Start New Project**. If you've worked on a
project before, it appears in the **Resume Existing Project** list instead.
Click a row to pick up exactly where you left off.

## 3. Describe your project

Give the project a **Project Title** and a one- or two-sentence
**Project Description** in plain English, e.g. *"We tracked monthly median
wait days after a scheduling improvement."* Click **Continue**.

:::{important}
Never type patient names, MRNs, or other direct identifiers into the
description box. The app scrubs obvious identifiers before sending anything
to AI features, but the safest data is data that was never typed in the
first place. See {doc}`concepts` for what the app does and doesn't send.
:::

Behind the scenes, the app tries to pre-fill some of the next screen's
answers from your description using AI. If it had to redact anything from
your text first, you'll see a banner telling you so.

## 4. Answer the intake questions

You'll see up to nine short questions (Q2-Q10; Q1 is the description you
already gave). Answer honestly, and whenever you're not sure pick
**"I'm not sure"** — it's always a valid answer, and the app falls back to a
safe default rather than blocking you. The exact question wording is in
{doc}`reference`.

For this walkthrough:

- **What are you measuring?** → *An average or median value*
- **Are you comparing before and after something?** → *No — I'm just
  describing one time period* (skip this if you truly are comparing two
  periods; comparing before/after leads to a different analysis).
- **Are you tracking over time, or comparing two groups?** → *Tracking over
  time*
- **What's the time unit?** → *Monthly*
- **How many time points (or rows) do you have?** → `12`
- **Which software should we put in the code export?** → whichever your
  mentor or department expects, or *All three* if unsure.

Click **Next** through each question, then **Continue** on the last one.

## 5. Upload your data

Click **Choose a CSV or Excel file** (or drag a file onto the drop zone).
Accepted types are `.csv`, `.xlsx`, and `.xls`, up to 50 MB. Click
**Upload CSV/Excel**.

## 6. Confirm column types

The app guesses each column's type — **Number**, **Category**, **Date**,
**ID**, or **Yes/No** — from its contents and its header name. Review the
**Data preview (first 5 rows)** table and correct any wrong guesses using the
dropdown next to each column, then click **Confirm Types**.

## 7. Review data quality

The app runs a set of automatic checks and shows any **Data Quality
Warnings** (mixed casing, missing data, outliers, gaps in your time series,
and similar) alongside the row count and missing-value percentage per
column. Check every warning's acknowledgement box to confirm you actually
looked at it; **Continue** stays disabled until you have.

If a check finds something more serious, a true **ERROR** like duplicate
patient IDs, the app blocks you outright and gives you a
**Re-upload corrected file** button instead of a checkbox. Errors can't be
acknowledged away; the underlying file has to change.

## 8. Choose your analysis

The app ranks three analyses based on your intake answers and marks one
**Recommended**. For this walkthrough (tracking a value over time, monthly,
12 points) it recommends **Run Chart**. You can pick any of the three shown;
the full list of six possible analyses is in {doc}`reference`.

## 9. Map your columns

Tell the app which uploaded column plays which role. For a run chart that's
a **Date column** and a **Value column**. Click **Run Analysis**.

## 10. Review your results

The app displays the figure, a results table (if applicable), and a
2‑sentence AI-written plain-language interpretation. If the AI had to
de-identify any text along the way, you'll see the same PHI banner as
before. Click **Edit & Review** once the interpretation has finished
loading.

## 11. Edit the report

Adjust the **Report Title**, **Figure Caption**, and **Interpretation** to
match your own voice. The AI text is a draft, not a final answer. Only the
fields you actually change are saved as edits, and the report keeps both the
original and edited text in its audit trail. Click **Save & Continue**.

## 12. Download and share

Click **Generate report** to build the report package, then:

- **Download Word (.docx)** or **Download PDF** for your own file, abstract,
  or presentation.
- **Share with mentor** to create a read-only review link. If you gave a
  mentor email back in the intake questions, this link was already created
  and emailed automatically; clicking here just re-shows it (or creates a
  fresh one for a different mentor email).

That's the whole workflow. See {doc}`how-to` for narrower tasks like
replacing a bad upload, revoking a mentor link, or updating admin settings.
