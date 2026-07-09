"""Sphinx configuration for QI Stat Studio documentation.

Two audiences, one build: a User Guide (Diataxis: tutorial / how-to /
reference / explanation, written for residents with no statistics
background) and a Developer Guide (same four Diataxis categories, written
for engineers extending or operating the app). See ``index.md`` for the
audience switcher.
"""

from __future__ import annotations

import datetime

project = "QI Stat Studio"
author = "QI Stat Studio contributors"
copyright = f"{datetime.date.today().year}, {author}"
release = "1.0.0"

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinx_design",
    "sphinxcontrib.mermaid",
]

source_suffix = {
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",     # ::: directive fences, cleaner than ```{directive}
    "deflist",         # definition lists for glossary-style reference pages
    "fieldlist",       # :Key: Value metadata lists
    "substitution",     # {{ variable }} content reuse
    "tasklist",        # - [ ] checkbox rendering (matches AGENTS.md conventions)
    "attrs_inline",    # {.class} inline attributes on Markdown spans
]
myst_heading_anchors = 3  # auto-generate #anchors up to h3 for cross-page linking

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Diataxis structure duplicated per audience; both trees are real files,
# not copies, so "developer" and "user" never fall out of sync silently —
# any duplication is a deliberate cross-link, checked by `make linkcheck`.
suppress_warnings = []

html_theme = "furo"
html_title = "QI Stat Studio Docs"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_show_sphinx = False

html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "top_of_page_buttons": [],
}

# Fail the build on broken cross-references — a broken :doc:/:ref: link is a
# documentation bug, not a warning to ignore.
nitpicky = False  # MyST + mixed prose docs generate false positives; rely on linkcheck instead
