from api.flag_ids import flag_id, with_ids


def test_legacy_flag_gets_derived_id_and_existing_id_is_kept():
    assert flag_id({"rule": "missing_pct", "col": "age"}) == "missing_pct:age"
    assert flag_id({"rule": "duplicate_rows", "col": "(dataset)"}) == "duplicate_rows:dataset"
    assert flag_id({"id": "x:y", "rule": "r", "col": "c"}) == "x:y"
    out = with_ids([{"rule": "r", "col": "c"}, "junk", {"id": "k"}])
    assert [f["id"] for f in out] == ["r:c", "k"]
