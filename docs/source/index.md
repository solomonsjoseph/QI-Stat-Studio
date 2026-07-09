# QI Stat Studio

QI Stat Studio is a guided statistical analysis app for medical residents running
quality-improvement (QI) projects. A resident describes a project in plain
language, uploads a CSV or Excel export, confirms data-quality checks, runs one
of six guide-recommended analyses, edits the interpretation, and downloads a
Word/PDF report or shares an in-browser mentor review link — without writing
or running any statistics code.

This site has two independent guides. Pick the one that matches what you're
doing right now; each is a complete, self-contained Diataxis set (tutorial,
how-to guides, reference, explanation), so you never need the other one to
finish a task.

::::{grid} 2
:gutter: 3

:::{grid-item-card} 🩺 User Guide
:link: user-guide/index
:link-type: doc

For residents and mentors running a QI project through the app: the 10-screen
wizard, the six analyses in plain English, uploading data, and sharing a
report.
:::

:::{grid-item-card} 🛠️ Developer Guide
:link: developer-guide/index
:link-type: doc

For engineers running, extending, testing, or deploying QI Stat Studio: local
setup, architecture, the data model, the API surface, and security design.
:::

::::

```{toctree}
:hidden:
:caption: User Guide

user-guide/index
user-guide/tutorial
user-guide/how-to
user-guide/reference
user-guide/concepts
```

```{toctree}
:hidden:
:caption: Developer Guide

developer-guide/index
developer-guide/getting-started
developer-guide/how-to
developer-guide/architecture
developer-guide/data-model
developer-guide/api-reference
developer-guide/security
developer-guide/testing
developer-guide/decisions
```
