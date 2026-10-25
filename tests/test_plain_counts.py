"""Counts read as plain English, and the advisor's data check has no stray punctuation."""
from api.data_changes import comment_block, step_line
from api.plural import plural


def test_plural():
    assert plural(1, "point") == "1 point"
    assert plural(0, "point") == "0 points"
    assert plural(4, "outlier") == "4 outliers"


def test_code_comments_have_no_doubled_or_stray_punctuation():
    step = {"op": "x", "description": "Changed text in period to lower case.", "rows_before": 6, "rows_after": 6,
            "rows_removed": 0, "cells_changed": 1, "warnings": ["Mixed case in 'period' column."]}
    line = step_line(step)
    assert ".." not in line
    for language in ("r", "spss", "sas"):
        assert ":." not in comment_block([line], language)
