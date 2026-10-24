from __future__ import annotations

import pandas as pd
from api.templates.before_after_pct import _coerce_binary_outcome


def _normal_group_values(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        return series.astype(str).str.strip().str.lower()
    return series


def _normal_group_value(series: pd.Series, value) -> str:
    if series.dtype == object:
        return str(value).strip().lower()
    return value




def _non_missing(series: pd.Series) -> pd.Series:
    present = series.notna()
    if series.dtype == object:
        present &= series.astype(str).str.strip().ne("")
    return present


def _date_parse_errors(df: pd.DataFrame, date_col: str) -> list[str]:
    raw = df[date_col]
    parsed = pd.to_datetime(raw, errors="coerce")
    bad = raw[_non_missing(raw) & parsed.isna()]
    if bad.empty:
        return []
    examples = ", ".join(str(v) for v in bad.drop_duplicates().head(5).tolist())
    return [f"Date column '{date_col}' contains values that cannot be parsed as dates: {examples}"]


def _numeric_parse_errors(df: pd.DataFrame, value_col: str, label: str = "Column") -> list[str]:
    raw = df[value_col]
    parsed = pd.to_numeric(raw, errors="coerce")
    bad = raw[_non_missing(raw) & parsed.isna()]
    if bad.empty:
        return []
    examples = ", ".join(str(v) for v in bad.drop_duplicates().head(5).tolist())
    return [f"{label} '{value_col}' contains non-numeric values: {examples}"]

def _time_series_points(df: pd.DataFrame, date_col: str, value_col: str, freq: str | None) -> int:
    dates = pd.to_datetime(df[date_col], errors="coerce")
    values = pd.to_numeric(df[value_col], errors="coerce")
    series = pd.DataFrame({date_col: dates, value_col: values}).dropna()
    if series.empty:
        return 0
    if freq:
        return int(series.set_index(date_col)[value_col].resample(freq).mean().dropna().shape[0])
    return int(series[date_col].nunique())


def aggregate_control_chart_frame(df: pd.DataFrame, params: dict, numerator_field: str) -> pd.DataFrame:
    date_col = params["date_col"]
    value_col = params[numerator_field]
    denominator_col = params.get("denominator_col")
    freq = params.get("freq") or "ME"
    work = pd.DataFrame(
        {
            date_col: pd.to_datetime(df[date_col], errors="coerce"),
            value_col: pd.to_numeric(df[value_col], errors="coerce"),
        }
    )
    # "n" counts real contributing rows per resampled period. resample() fills
    # calendar gaps with empty buckets whose sum/count aggregations are 0, not
    # NaN, so a plain .dropna() keeps those phantom zero-data periods; filtering
    # on n > 0 drops periods with no uploaded rows instead of charting them as a
    # measured zero.
    agg_spec = {"num": (value_col, "sum"), "n": (value_col, "count")}
    if denominator_col:
        work[denominator_col] = pd.to_numeric(df[denominator_col], errors="coerce")
        agg_spec["denom"] = (denominator_col, "sum")
    else:
        agg_spec["denom"] = (value_col, "count")
    aggregated = work.dropna().set_index(date_col).resample(freq).agg(**agg_spec).dropna()
    return aggregated[aggregated["n"] > 0].drop(columns="n").reset_index()


def _validate_denominator(df: pd.DataFrame, denominator_col: str | None) -> list[str]:
    if not denominator_col:
        return []
    denom = pd.to_numeric(df[denominator_col], errors="coerce")
    if denom.isna().any() or (denom <= 0).any():
        return [f"Denominator column '{denominator_col}' must contain only positive values"]
    return []

def _validate_p_chart_numerator(df: pd.DataFrame, numerator_col: str, denominator_col: str | None) -> list[str]:
    numerator = pd.to_numeric(df[numerator_col], errors="coerce")
    if denominator_col:
        denominator = pd.to_numeric(df[denominator_col], errors="coerce")
        mask = numerator.notna() & denominator.notna()
        if (numerator[mask] > denominator[mask]).any():
            return [f"Numerator column '{numerator_col}' must not exceed the denominator column '{denominator_col}' in any row"]
        return []
    present = numerator.dropna()
    if not present.isin([0, 1]).all():
        return [f"Numerator column '{numerator_col}' must contain only 0/1 values when no denominator column is supplied"]
    return []


def _validate_non_negative(df: pd.DataFrame, col: str, label: str) -> list[str]:
    values = pd.to_numeric(df[col], errors="coerce").dropna()
    if (values < 0).any():
        return [f"{label} '{col}' must not contain negative values"]
    return []


def validate_analysis_inputs(template: str, df: pd.DataFrame, params: dict) -> list[str]:
    errors: list[str] = []

    if template == "descriptive_summary":
        for col in params["value_cols"]:
            values = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(values) < 2:
                errors.append(f"Column '{col}' must have at least 2 non-null numeric observations")
        return errors

    if template == "before_after_mean":
        group_col = params["group_col"]
        value_col = params["value_col"]
        groups = _normal_group_values(df[group_col])
        pre_val = _normal_group_value(df[group_col], params["pre_val"])
        post_val = _normal_group_value(df[group_col], params["post_val"])
        present = set(groups.dropna().unique())
        if pre_val not in present:
            errors.append(f"Pre group '{params['pre_val']}' is not present in column '{group_col}'")
        if post_val not in present:
            errors.append(f"Post group '{params['post_val']}' is not present in column '{group_col}'")
        values = pd.to_numeric(df[value_col], errors="coerce")
        pre_n = int(values[groups == pre_val].dropna().shape[0])
        post_n = int(values[groups == post_val].dropna().shape[0])
        if pre_n < 2 or post_n < 2:
            errors.append(
                f"Before/after mean analysis requires at least 2 non-null values in both groups; found {pre_n} pre and {post_n} post"
            )
        return errors

    if template == "before_after_pct":
        group_col = params["group_col"]
        outcome_col = params["outcome_col"]
        groups = _normal_group_values(df[group_col])
        pre_val = _normal_group_value(df[group_col], params["pre_val"])
        post_val = _normal_group_value(df[group_col], params["post_val"])
        present = set(groups.dropna().unique())
        if pre_val not in present:
            errors.append(f"Pre group '{params['pre_val']}' is not present in column '{group_col}'")
        if post_val not in present:
            errors.append(f"Post group '{params['post_val']}' is not present in column '{group_col}'")
        if pre_val == post_val:
            errors.append(f"Pre group and post group must be different (both were '{params['pre_val']}')")
            return errors
        try:
            values = _coerce_binary_outcome(df[outcome_col], outcome_col)
        except ValueError as exc:
            errors.append(str(exc))
            return errors
        pre_n = int(values[groups == pre_val].dropna().shape[0])
        post_n = int(values[groups == post_val].dropna().shape[0])
        if pre_n < 1 or post_n < 1:
            errors.append(
                f"Before/after proportion analysis requires at least one non-null binary outcome in both groups; found {pre_n} pre and {post_n} post"
            )
        return errors

    if template == "before_after_paired":
        id_col = params["id_col"]
        group_col = params["group_col"]
        value_col = params["value_col"]
        if id_col not in df.columns:
            errors.append(f"ID column '{id_col}' is not present in dataset")
        if group_col not in df.columns:
            errors.append(f"Group column '{group_col}' is not present in dataset")
        if value_col not in df.columns:
            errors.append(f"Value column '{value_col}' is not present in dataset")
        if errors:
            return errors

        groups = _normal_group_values(df[group_col])
        pre_val = _normal_group_value(df[group_col], params["pre_val"])
        post_val = _normal_group_value(df[group_col], params["post_val"])
        present = set(groups.dropna().unique())
        if pre_val not in present:
            errors.append(f"Pre group '{params['pre_val']}' is not present in column '{group_col}'")
        if post_val not in present:
            errors.append(f"Post group '{params['post_val']}' is not present in column '{group_col}'")
        if pre_val == post_val:
            errors.append(f"Pre group and post group must be different (both were '{params['pre_val']}')")
            return errors

        vals = pd.to_numeric(df[value_col], errors="coerce")
        pre_ids = set(df[(groups == pre_val) & vals.notna()][id_col])
        post_ids = set(df[(groups == post_val) & vals.notna()][id_col])
        n_pairs = len(pre_ids & post_ids)
        if n_pairs < 2:
            errors.append(
                f"Paired analysis requires at least 2 complete pairs with values in both groups; found {n_pairs}"
            )
        return errors

    if template == "run_chart":
        errors.extend(_date_parse_errors(df, params["date_col"]))
        errors.extend(_numeric_parse_errors(df, params["value_col"]))
        if errors:
            return errors
        points = _time_series_points(df, params["date_col"], params["value_col"], params.get("freq") or "ME")
        if points < 2:
            errors.append(f"Run chart requires at least 2 time points after date/value coercion; found {points}")
        return errors

    if template == "p_chart":
        errors.extend(_date_parse_errors(df, params["date_col"]))
        errors.extend(_numeric_parse_errors(df, params["numerator_col"], "Numerator column"))
        errors.extend(_validate_denominator(df, params.get("denominator_col")))
        errors.extend(_validate_non_negative(df, params["numerator_col"], "Numerator column"))
        errors.extend(_validate_p_chart_numerator(df, params["numerator_col"], params.get("denominator_col")))
        return errors

    if template == "u_c_chart":
        errors.extend(_date_parse_errors(df, params["date_col"]))
        errors.extend(_numeric_parse_errors(df, params["count_col"], "Count column"))
        errors.extend(_validate_denominator(df, params.get("denominator_col")))
        errors.extend(_validate_non_negative(df, params["count_col"], "Count column"))
        return errors

    return errors
