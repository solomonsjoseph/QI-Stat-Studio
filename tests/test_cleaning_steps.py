import json

import numpy as np
import pandas as pd
import pytest

from api.cleaning_steps import StepError, STEP_VOCABULARY, apply_steps, describe_step, validate_steps


def make():
    return pd.DataFrame({
        "sex": [" M", "F ", "male", "Female", None, "M"],
        "age": ["30", "41", "x", "55", "62", "30"],
        "dose": [1, 2, 3, 4, 5, 1],
        "when": ["2024-01-02", "2024-02-03", "bad", "2024-03-04", None, "2024-01-02"],
    })


def run(steps, df=None):
    return apply_steps(make() if df is None else df, steps)


def test_recode_and_merge():
    out, rep = run([
        {"op": "trim", "columns": ["sex"]},
        {"op": "recode", "column": "sex", "mapping": {"male": "M", "Female": "F"}},
    ])
    assert list(out["sex"].fillna("NA")) == ["M", "F", "M", "F", "NA", "M"]
    assert rep[1]["cells_changed"] == 2 and rep[0]["cells_changed"] == 2
    out, rep = run([{"op": "merge_values", "column": "dose", "values": [1, 2], "into": 0}])
    assert list(out["dose"]) == [0, 0, 3, 4, 5, 0] and rep[0]["rows_changed"] == 3


def test_recode_is_simultaneous_and_matches_text_to_number():
    out, _ = run([{"op": "recode", "column": "dose", "mapping": {"1": 2, "2": 1}}])
    assert list(out["dose"]) == [2, 1, 3, 4, 5, 2]


def test_change_case():
    out, _ = run([{"op": "change_case", "columns": ["sex"], "mode": "upper"}])
    assert out["sex"][2] == "MALE" and pd.isna(out["sex"][4])


def test_retype():
    with pytest.raises(StepError, match="step 0.*numbers"):
        run([{"op": "retype", "column": "age", "to": "numeric"}])
    out, rep = run([{"op": "retype", "column": "age", "to": "numeric", "errors": "coerce"}])
    assert out["age"].isna().sum() == 1 and out["age"].dtype.kind == "f"
    out, _ = run([{"op": "retype", "column": "when", "to": "date", "errors": "coerce", "format": "%Y-%m-%d"}])
    assert str(out["when"].dtype).startswith("datetime") and out["when"].isna().sum() == 2
    out, _ = run([{"op": "retype", "column": "dose", "to": "string"}])
    assert out["dose"][0] == "1"
    out, _ = run([{"op": "retype", "column": "sex", "to": "category"}])
    assert str(out["sex"].dtype) == "category"


def test_rename_and_drop_column():
    out, rep = run([{"op": "rename_column", "column": "dose", "new_name": "mg"}, {"op": "drop_column", "column": "when"}])
    assert "mg" in out and "dose" not in out and "when" not in out
    assert rep[0]["rows_changed"] == 0
    with pytest.raises(StepError, match="already exists"):
        run([{"op": "rename_column", "column": "dose", "new_name": "age"}])


def test_set_value_and_fill():
    out, rep = run([{"op": "set_value", "column": "sex", "value": "U", "where": {"column": "sex", "op": "isnull"}}])
    assert out["sex"][4] == "U" and rep[0]["cells_changed"] == 1
    out, rep = run([{"op": "set_value", "column": "dose", "value": 9}])
    assert (out["dose"] == 9).all() and rep[0]["cells_changed"] == 6


def test_drop_duplicates():
    out, rep = run([{"op": "drop_duplicates", "subset": ["age", "dose"]}])
    assert len(out) == 5 and rep[0]["rows_before"] == 6 and rep[0]["rows_after"] == 5
    out, _ = run([{"op": "trim", "columns": ["sex"]}, {"op": "drop_duplicates"}])
    assert len(out) == 5


@pytest.mark.parametrize("where,expected", [
    ({"column": "dose", "op": "eq", "value": 3}, [3]),
    ({"column": "dose", "op": "ne", "value": 3}, [1, 2, 4, 5, 1]),
    ({"column": "dose", "op": "lt", "value": 2}, [1, 1]),
    ({"column": "dose", "op": "le", "value": 2}, [1, 2, 1]),
    ({"column": "dose", "op": "gt", "value": 4}, [5]),
    ({"column": "dose", "op": "ge", "value": 4}, [4, 5]),
    ({"column": "dose", "op": "in", "value": [1, 5]}, [1, 5, 1]),
    ({"column": "dose", "op": "not_in", "value": [1, 5]}, [2, 3, 4]),
    ({"column": "sex", "op": "isnull"}, [5]),
    ({"column": "sex", "op": "notnull"}, [1, 2, 3, 4, 1]),
    ({"column": "sex", "op": "contains", "value": "ale"}, [3, 4]),
    ({"all": [{"column": "dose", "op": "ge", "value": 2}, {"column": "dose", "op": "le", "value": 4}]}, [2, 3, 4]),
    ({"any": [{"column": "dose", "op": "eq", "value": 1}, {"column": "sex", "op": "isnull"}]}, [1, 5, 1]),
])
def test_drop_rows_conditions(where, expected):
    out, rep = run([{"op": "drop_rows", "where": where}])
    # rows matching are removed, so the survivors are the complement
    all_doses = [1, 2, 3, 4, 5, 1]
    remaining = list(out["dose"])
    removed = list(all_doses)
    for d in remaining:
        removed.remove(d)
    assert sorted(removed) == sorted(expected)
    assert rep[0]["rows_changed"] == len(expected)


def test_bad_comparison_is_step_error():
    with pytest.raises(StepError, match="step 0"):
        run([{"op": "drop_rows", "where": {"column": "sex", "op": "gt", "value": 3}}])


def test_errors_name_step_index():
    with pytest.raises(StepError, match="step 1.*unknown op"):
        run([{"op": "trim", "columns": ["sex"]}, {"op": "exec", "code": "1"}])
    with pytest.raises(StepError, match="step 1.*unknown column"):
        run([{"op": "trim", "columns": ["sex"]}, {"op": "drop_column", "column": "nope"}])
    with pytest.raises(StepError, match="unexpected keys"):
        validate_steps([{"op": "drop_column", "column": "a", "code": "x"}])
    with pytest.raises(StepError, match="missing"):
        validate_steps([{"op": "recode", "column": "a"}])
    with pytest.raises(StepError):
        validate_steps([{"op": "drop_rows", "where": {"column": "a", "op": "eval", "value": 1}}])
    with pytest.raises(StepError):
        validate_steps("drop everything")


def test_all_or_nothing_and_immutable():
    df = make()
    snap = df.copy(deep=True)
    with pytest.raises(StepError):
        apply_steps(df, [{"op": "trim", "columns": ["sex"]}, {"op": "drop_column", "column": "nope"}])
    pd.testing.assert_frame_equal(df, snap)
    apply_steps(df, [{"op": "drop_rows", "where": {"column": "dose", "op": "eq", "value": 1}},
                     {"op": "recode", "column": "sex", "mapping": {"F ": "F"}}])
    pd.testing.assert_frame_equal(df, snap)


def test_idempotent_ops():
    steps = [{"op": "trim", "columns": ["sex"]}, {"op": "change_case", "columns": ["sex"], "mode": "lower"},
             {"op": "drop_duplicates"}, {"op": "drop_rows", "where": {"column": "dose", "op": "gt", "value": 4}}]
    once, _ = run(steps)
    twice, rep = apply_steps(once, steps)
    pd.testing.assert_frame_equal(once, twice)
    assert all(r["rows_changed"] == 0 and r["cells_changed"] == 0 for r in rep)


def test_report_shape_and_determinism_and_json_roundtrip():
    steps = [{"op": "trim", "columns": ["sex"], "warning_ids": ["w1"], "note": "stray spaces"},
             {"op": "drop_rows", "where": {"column": "age", "op": "eq", "value": "x"}}]
    rt = json.loads(json.dumps(steps))
    assert rt == steps
    a, ra = run(steps)
    b, rb = run(rt)
    pd.testing.assert_frame_equal(a, b)
    assert ra == rb
    assert set(ra[0]) == {"op", "description", "no_effect", "rows_before", "rows_after", "rows_changed",
                          "cells_changed", "columns", "warning_ids", "note"}
    assert ra[0]["warning_ids"] == ["w1"] and ra[0]["note"] == "stray spaces"
    assert ra[1]["rows_before"] == 6 and ra[1]["rows_after"] == 5 and ra[1]["columns"] == ["age"]
    json.dumps(ra)


def test_describe_and_vocabulary():
    assert describe_step({"op": "drop_rows", "where": {"column": "age", "op": "lt", "value": 18}}) == \
        "Removed rows where age is less than 18."
    for op in ["recode", "merge_values", "trim", "change_case", "retype", "rename_column",
               "set_value", "drop_duplicates", "drop_rows", "drop_column"]:
        assert op in STEP_VOCABULARY


def test_empty_steps():
    df = make()
    out, rep = apply_steps(df, [])
    pd.testing.assert_frame_equal(out, df)
    assert rep == [] and out is not df


# ---------- review fixes ----------

def test_step_errors_never_quote_cell_values():
    df = pd.DataFrame({"age": ["41", "John Smith", "Jane Doe"], "when": ["Mary Major", "2024-01-01", None]})
    for step in ({"op": "retype", "column": "age", "to": "numeric"},
                 {"op": "retype", "column": "when", "to": "date"}):
        with pytest.raises(StepError) as e:
            apply_steps(df, [step])
        assert "John" not in str(e.value) and "Smith" not in str(e.value) and "Mary" not in str(e.value)
        assert "could not be converted" in str(e.value) and "'age'" in str(e.value) or "'when'" in str(e.value)
    mixed = pd.DataFrame({"x": ["Zed Name", 3, 4]})
    with pytest.raises(StepError) as e:
        apply_steps(mixed, [{"op": "drop_rows", "where": {"column": "x", "op": "gt", "value": 2}}])
    assert "Zed" not in str(e.value)


def test_string_keys_match_numeric_cells():
    df = pd.DataFrame({"g": [1, 2, 1.0, None], "t": ["a", "b", "a", "c"]})
    out, rep = apply_steps(df, [{"op": "recode", "column": "g", "mapping": {"1": "one"}}])
    assert list(out["g"].iloc[[0, 2]]) == ["one", "one"]
    out, _ = apply_steps(df, [{"op": "merge_values", "column": "g", "values": ["1", "2"], "into": "x"}])
    assert list(out["g"].iloc[:3]) == ["x", "x", "x"]
    out, _ = apply_steps(df, [{"op": "drop_rows", "where": {"column": "g", "op": "in", "value": ["1.0"]}}])
    assert len(out) == 2


def test_no_effect_flag():
    df = pd.DataFrame({"g": [1, 2]})
    _, rep = apply_steps(df, [{"op": "recode", "column": "g", "mapping": {"9": "nine"}},
                              {"op": "recode", "column": "g", "mapping": {"1": 5}}])
    assert rep[0]["no_effect"] is True and "matched no rows" in rep[0]["description"]
    assert rep[1]["no_effect"] is False and "matched no rows" not in rep[1]["description"]


def test_ne_and_not_in_keep_missing_rows_out_of_the_match():
    df = pd.DataFrame({"d": [1, 2, None]})
    out, _ = apply_steps(df, [{"op": "drop_rows", "where": {"column": "d", "op": "ne", "value": 1}}])
    assert len(out) == 2 and out["d"].isna().sum() == 1
    out, _ = apply_steps(df, [{"op": "drop_rows", "where": {"column": "d", "op": "not_in", "value": [1]}}])
    assert len(out) == 2 and out["d"].isna().sum() == 1
    assert "missing values are kept" in describe_step(
        {"op": "drop_rows", "where": {"column": "d", "op": "ne", "value": 1}})
    assert "missing values" in STEP_VOCABULARY


def test_size_caps():
    step = {"op": "trim", "columns": ["a"]}
    with pytest.raises(StepError, match="at most 100"):
        validate_steps([step] * 101)
    with pytest.raises(StepError, match="1000 entries"):
        validate_steps([{"op": "recode", "column": "a", "mapping": {str(i): 1 for i in range(1001)}}])
    with pytest.raises(StepError, match="1000 entries"):
        validate_steps([{"op": "merge_values", "column": "a", "values": list(range(1001)), "into": 1}])
    with pytest.raises(StepError, match="500 characters"):
        validate_steps([{"op": "set_value", "column": "a", "value": "x" * 501}])
    validate_steps([step] * 100)


def test_index_is_renumbered_and_input_untouched():
    df = pd.DataFrame({"a": [1, 2, 3]}, index=[10, 20, 30])
    steps = [{"op": "drop_rows", "where": {"column": "a", "op": "eq", "value": 1}}]
    out, _ = apply_steps(df, steps)
    assert list(out.index) == [0, 1] and list(df.index) == [10, 20, 30] and len(df) == 3
