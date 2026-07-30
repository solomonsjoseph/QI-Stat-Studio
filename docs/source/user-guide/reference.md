# Reference

Exact wording and behavior, for looking things up rather than reading start
to finish.

## The 10 screens

| # | Screen | What happens here |
|---|--------|--------------------|
| 1 | Landing | Sign in, start a new project, or resume/archive an existing one. |
| 2 | Project Description | Title and a plain-language description of the project; triggers AI intake pre-fill. |
| 3 | Intake Questions | Nine short questions (Q2–Q10) that decide which analysis gets recommended. |
| 4 | Upload | Upload a CSV or Excel file, then confirm the detected column types. |
| 5 | Data Review | Row count, missing-value percentages, and data-quality warnings/errors to acknowledge or fix. |
| 6 | Analysis Selection | Pick from three ranked analyses; one is marked Recommended. |
| 7 | Parameter Selection | Map uploaded columns to the fields the chosen analysis needs. |
| 8 | Results | The figure, table, and an AI-drafted plain-language interpretation. |
| 9 | Edit & Review | Edit the report title, figure caption, and interpretation. |
| 10 | Download & Share | Generate the report, download Word/PDF, and share a mentor review link. |

The progress bar counts 9 steps (Description through Download). Landing
itself isn't numbered, since it's where you choose *which* project to work
on.

## Intake questions, exact wording

Q1 is your project description from screen 2, reused here. It isn't asked
again. "I'm not sure" is always an available answer.

`````{list-table}
:header-rows: 1
:widths: 8 30 47 15

* - Key
  - Question
  - Options / input
  - When it's asked
* - Q2
  - What are you measuring?
  - A rate of events over time (infections per 1,000 catheter-days) · A
    percentage or proportion (percent of patients screened) · A count
    (number of falls per month) · An average or median value (average LDL)
    · A yes/no outcome (did the patient get a flu shot) · Something else /
    not sure
  - Always
* - Q3
  - Are you comparing before and after something?
  - Yes — before and after an intervention · No — I'm just describing one
    time period · More than two periods (phases) · I'm not sure
  - Always
* - Q4
  - Are you tracking over time, or comparing two groups?
  - Tracking over time (months, weeks, days) · Comparing groups at one
    point in time · Both · I'm not sure
  - Always
* - Q5
  - What's the time unit?
  - Daily · Weekly · Monthly · One row per patient · Other · I'm not sure
  - Always
* - Q6
  - How many time points (or rows) do you have?
  - Number. *Run and control charts work best with 12 or more time points.
    Under 12, we'll recommend a simpler run chart instead of a control
    chart.*
  - Always
* - Q7
  - What was the intervention and when did it start?
  - Intervention description (optional, free text) + Intervention date (if
    known). Pre-filled from your project description.
  - Skipped when Q3 = "No — I'm just describing one time period"
* - Q8
  - Who are you comparing?
  - Same unit pre vs. post · Intervention vs. control · Subgroups · I'm not
    sure
  - Skipped when Q3 = "No — I'm just describing one time period"
* - Q9
  - Which software should we put in the code export?
  - R · SPSS · SAS · All three · I'm not sure (defaults to including all
    three). You never run this code yourself. The app has already run the
    analysis; this only affects the exported supplement.
  - Always
* - Q10
  - Your mentor and timeline (optional)
  - Mentor's email (so they get a share link) + Abstract deadline. Saving a
    mentor email here automatically creates and emails the share link. You
    don't have to also click "Share with mentor" later, though you can.
  - Always, optional
`````

## The six analyses

| Analysis | Use it when | What the tool does |
|----------|-------------|---------------------|
| **Descriptive Summary** | You need a one-period summary or Table 1. | Reports n, mean, SD, and median per variable, optionally split by group. |
| **Before/After: Mean** | You're comparing an average or median before vs. after. | Checks normality (Shapiro-Wilk) and equal variance (Levene), then automatically picks a t-test or a Wilcoxon rank-sum test. |
| **Before/After: Proportion** | You're comparing a percentage or yes/no rate before vs. after. | Automatically picks a chi-square test or Fisher's exact test based on expected cell counts. |
| **Run Chart** | You're tracking a value over time, especially with fewer than 12 points. | Plots the value over time with a median line and flags run (≥8 same-side points) and trend (≥6 consecutive same-direction) signals. |
| **p-Chart** | You're tracking a percentage/proportion over time with 12+ points. | 3-sigma control limits computed from each period's numerator and denominator. |
| **u/c-Chart** | You're tracking a rate or count over time with 12+ points. | Uses a u-chart when the denominator varies period to period, or a c-chart when it's stable; both use 3-sigma control limits. |

The app always runs the statistics itself. The R/SPSS/SAS code from Q9 is
only an *export-only* record of what was already done, for your supplement
or your mentor.

## What "I'm not sure" does

Every question accepts "I'm not sure" without blocking you. For Q6 (time
points), leaving it unset or unclear falls back to a run chart instead of a
control chart. For Q9 (code export), "I'm not sure" exports all three
languages so you're covered either way. For every other question, "I'm not
sure" is simply one more input to the analysis recommendation and never
stops you from continuing.
