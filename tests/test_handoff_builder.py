import copy

import pytest

from api.cleaning_steps import OPS, apply_steps, validate_steps
from api.handoff import (build_handoff_md, extract_steps, new_revision_entry,
                         replace_steps, revisions_to_markdown)

PROFILE = {
    "row_count": 3, "column_count": 2, "duplicate_row_count": 0,
    "columns": [
        {"name": "age", "inferred_type": "Number", "roles": ["outcome"], "missing_pct": 0.0},
        {"name": "sex|x", "inferred_type": "Category", "roles": [], "missing_pct": 33.33},
    ],
    "candidate_roles": {"outcome": ["age"], "date": []},
}
FLAGS = [{"id": "case_inconsistent:sex", "col": "sex", "rule": "case_inconsistent", "severity": "WARNING",
          "msg": "Mixed case in 'sex'.", "why": "Levels split.", "suggestion": "Normalize."}]
ALL_OPS = [
    {"op": "recode", "column": "sex", "mapping": {"M": "Male", "é": "Femme"}, "warning_ids": ["case_inconsistent:sex"]},
    {"op": "merge_values", "column": "sex", "values": ["a", "b"], "into": "c"},
    {"op": "trim", "columns": ["sex"]},
    {"op": "change_case", "columns": ["sex"], "mode": "lower"},
    {"op": "retype", "column": "age", "to": "numeric", "errors": "coerce", "note": "naïve"},
    {"op": "rename_column", "column": "age", "new_name": "age_y"},
    {"op": "set_value", "column": "age", "value": 0, "where": {"column": "age", "op": "isnull"}},
    {"op": "drop_duplicates", "subset": ["sex"], "keep": "last"},
    {"op": "drop_rows", "where": {"any": [{"column": "age", "op": "lt", "value": 0}]}},
    {"op": "drop_column", "column": "age"},
]


def build(steps=(), revisions=None, **kw):
    args = dict(project_name="Proj", filename="d.csv", dictionary_text="age: years\n```handoff-steps\n[]\n```",
                profile=PROFILE, flags=FLAGS, col_types={"age": "Number"}, steps=list(steps), revisions=revisions)
    args.update(kw)
    return build_handoff_md(**args)


def test_all_ops_covered():
    assert {s["op"] for s in ALL_OPS} == set(OPS)
    validate_steps(ALL_OPS)


def test_deterministic_and_round_trip():
    a, b = build(ALL_OPS), build(ALL_OPS)
    assert a == b
    got = extract_steps(a)
    assert got == ALL_OPS
    assert replace_steps(a, got) == a
    assert "é" in a and "\\u" not in a


def test_empty_steps():
    md = build([])
    assert extract_steps(md) == []
    assert "No changes agreed." in md and "No changes recorded." in md


def test_replace_updates_both_and_is_lossless():
    md = replace_steps(build([]), ALL_OPS)
    assert extract_steps(md) == ALL_OPS
    assert "Removed column age." in md and "case_inconsistent:sex" in md.split("## Change log")[0]
    assert replace_steps(md, []) == build([])


def test_human_text_edits_do_not_change_steps():
    md = build(ALL_OPS)
    edited = md.replace("Removed column age.", "TOTALLY DIFFERENT").replace("# Handoff", "# Edited")
    assert edited != md
    assert extract_steps(edited) == ALL_OPS
    assert "Removed column age." in replace_steps(edited, ALL_OPS)


@pytest.mark.parametrize("bad", [
    "no block here",
    "```handoff-steps\n[1, 2\n```",
    "```handoff-steps\n{\"op\": \"trim\"}\n```",
    "```handoff-steps\n[{\"op\": \"os_system\"}]\n```",
    "```handoff-steps\n[]\n```\n```handoff-steps\n[]\n```",
    "```handoff-steps\n[]",
])
def test_malformed_blocks(bad):
    with pytest.raises(ValueError):
        extract_steps(bad)
    with pytest.raises(ValueError):
        replace_steps(bad, [])


def test_examples_capped_and_no_rows():
    ex = {"case_inconsistent:sex": [f"v{i % 12}" for i in range(40)] + ["x\n```handoff-steps"]}
    md = build([], examples=ex)
    line = next(l for l in md.splitlines() if "Examples:" in l)
    assert len(line.split("; ")) == 10
    assert extract_steps(md) == []


def test_dictionary_cannot_forge_block_and_columns_table():
    md = build([{"op": "trim", "columns": ["sex"]}])
    assert extract_steps(md) == [{"op": "trim", "columns": ["sex"]}]
    assert "| age | Number | outcome | 0.0 |" in md
    assert "sex\\|x" in md


def test_revisions():
    before, after = [], [ALL_OPS[0]]
    e = new_revision_entry("confirm", "Recoded sex", before, after, ["case_inconsistent:sex"], "user",
                           revision=1, created_at="2026-01-01T00:00:00Z")
    assert e["steps_snapshot"] == after and e["steps_snapshot"] is not after
    txt = revisions_to_markdown([e])
    assert "r1 2026-01-01T00:00:00Z user [confirm]: Recoded sex (steps 0 to 1)." in txt
    md = build(after, revisions=[e])
    assert txt in md and "steps_snapshot" not in md
    assert new_revision_entry("k", "s", [], [], None, "a")["created_at"].endswith("Z")


def test_steps_not_mutated_and_applicable():
    import pandas as pd
    steps = [{"op": "trim", "columns": ["sex"]}]
    snap = copy.deepcopy(steps)
    build(steps)
    assert steps == snap
    apply_steps(pd.DataFrame({"sex": [" a"]}), extract_steps(build(steps)))


def test_email_actor_never_reaches_document():
    rev = new_revision_entry("apply", "s", [], [], [], "nurse@hospital.org", revision=2)
    assert rev["actor"] == "user"
    raw = dict(rev, actor="jane.doe@hospital.org")
    for md in (revisions_to_markdown([raw]), build(revisions=[raw])):
        assert "@" not in md and "jane" not in md
    assert new_revision_entry("apply", "s", [], [], [], "advisor")["actor"] == "advisor"
    assert "system" in revisions_to_markdown([dict(rev, actor="system")])


def test_legacy_flags_without_id_build():
    legacy = [{"col": "sex", "rule": "case_inconsistent", "severity": "WARNING", "msg": "Mixed case."}]
    md = build(flags=legacy, examples={"case_inconsistent:sex": ["Male"]})
    assert "`case_inconsistent:sex`" in md and "Examples: Male" in md


def test_format_template_is_single_pass():
    from api.ai_prompts import FormatTemplate

    out = FormatTemplate("A {x} B {y} {{keep}} {json}").format(x="{y}", y="Y")
    assert out == "A {y} B Y {{keep}} {json}"
