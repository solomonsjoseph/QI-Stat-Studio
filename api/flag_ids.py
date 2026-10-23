"""Stable ids for quality flags, including flags stored before ids existed."""


def flag_id(flag):
    """Return the flag's id, deriving "<rule>:<col>" for legacy flags (dataset-level uses "dataset")."""
    fid = flag.get("id")
    if fid:
        return fid
    col = flag.get("col")
    if not col or col == "(dataset)":
        col = "dataset"
    return "%s:%s" % (flag.get("rule"), col)


def with_ids(flags):
    """Copy of flags (dicts only) where every flag has an `id`."""
    return [dict(f, id=flag_id(f)) for f in (flags or []) if isinstance(f, dict)]
