#!/usr/bin/env python3
"""Checks docs pages against the repo standard's documentation rules.

Rules for every Markdown or MDX page under docs/:
  * it lives in an allowed place: docs/index, docs/{tutorials,how-to,
    reference,explanation}/ or docs/dev/;
  * it starts with front matter holding title, description, type and
    audience;
  * type is one of tutorial, how-to, reference, explanation, overview, and
    matches the folder (index pages may be overview);
  * audience is a list drawn from user, developer, admin; pages under
    docs/dev/ include developer;
  * the page has one H1 equal to the front matter title, or, with --no-h1
    (sites such as Starlight that render the title), no H1 at all.

Usage: check_docs.py [--no-h1] FILE...  (pre-commit passes the changed files)
"""

import re
import sys
from pathlib import PurePosixPath

TYPES = {"tutorial", "how-to", "reference", "explanation", "overview"}
AUDIENCES = {"user", "developer", "admin"}
FOLDER_TYPE = {
    "tutorials": "tutorial",
    "how-to": "how-to",
    "reference": "reference",
    "explanation": "explanation",
}
REQUIRED = ("title", "description", "type", "audience")


def parse_front_matter(text: str) -> dict[str, str] | None:
    """Returns the simple key: value pairs of a leading YAML block."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    fields = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def parse_list(value: str) -> list[str]:
    """Parses an inline YAML list such as [user, developer]."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip().strip("'\"") for item in value.split(",") if item.strip()]


def body_h1s(text: str) -> list[str]:
    """Returns the H1 headings outside front matter and fenced code blocks."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        text = text[end + 4 :] if end != -1 else text
    headings, fenced = [], False
    for line in text.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        elif not fenced:
            match = re.match(r"^# (.+?)\s*#*\s*$", line)
            if match:
                headings.append(match.group(1))
    return headings


def check(path_str: str, no_h1: bool = False) -> list[str]:
    """Returns the rule violations for one file."""
    path = PurePosixPath(path_str)
    parts = path.parts
    errors = []
    if len(parts) < 2 or parts[0] != "docs":
        return errors
    section = parts[1] if len(parts) > 2 else None
    is_index = path.stem == "index"
    if section is None and not is_index:
        errors.append("top-level docs pages other than docs/index are not allowed")
    elif section is not None and section not in FOLDER_TYPE and section != "dev":
        errors.append(
            f"'docs/{section}/' is not a docs section; use tutorials, how-to, "
            "reference, explanation or dev"
        )

    with open(path_str, encoding="utf-8") as handle:
        text = handle.read()
    fields = parse_front_matter(text)
    if fields is None:
        return [*errors, "missing front matter (title, description, type, audience)"]
    errors += [f"front matter lacks '{key}'" for key in REQUIRED if not fields.get(key)]

    page_type = fields.get("type", "").strip("'\"")
    if page_type and page_type not in TYPES:
        errors.append(f"type '{page_type}' is not one of {sorted(TYPES)}")
    expected = FOLDER_TYPE.get(section or "")
    if (
        expected
        and page_type
        and page_type != expected
        and not (is_index and page_type == "overview")
    ):
        errors.append(
            f"type '{page_type}' does not match folder '{section}/' ({expected})"
        )

    audience = parse_list(fields.get("audience", ""))
    unknown = [a for a in audience if a not in AUDIENCES]
    if unknown:
        errors.append(f"unknown audience {unknown}; use {sorted(AUDIENCES)}")
    if section == "dev" and audience and "developer" not in audience:
        errors.append("pages under docs/dev/ must include audience 'developer'")

    title = fields.get("title", "").strip("'\"")
    h1s = body_h1s(text)
    if no_h1:
        if h1s:
            errors.append("this repo renders the title itself; remove the H1")
    elif len(h1s) != 1:
        errors.append(f"expected exactly one H1 equal to the title, found {len(h1s)}")
    elif title and h1s[0] != title:
        errors.append(f"H1 '{h1s[0]}' differs from title '{title}'")
    return errors


def main(argv: list[str]) -> int:
    """Checks every file and prints violations."""
    no_h1 = "--no-h1" in argv
    failed = False
    for name in (arg for arg in argv if arg != "--no-h1"):
        for error in check(name, no_h1):
            print(f"{name}: {error}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
