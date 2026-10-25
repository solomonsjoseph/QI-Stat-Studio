"""Text-column check that holds on every pandas version: pandas 3 reads text as its own str dtype, not object."""

from __future__ import annotations

import pandas as pd


def is_text(series: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
