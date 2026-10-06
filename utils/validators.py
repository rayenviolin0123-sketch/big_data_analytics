"""Input validation and dtype predicates shared by the services."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

import config

# 2024-01-31, 31/01/2024, 2024-01-31 12:30:00, 2024-01-31T12:30:00Z ...
DATE_RE = re.compile(
    r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}"
    r"([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?)?\s*$"
)


def is_text(s: pd.Series) -> bool:
    if isinstance(s.dtype, pd.CategoricalDtype):
        return False
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


def is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def is_datetime(s: pd.Series) -> bool:
    return pd.api.types.is_datetime64_any_dtype(s)


def is_categorical_like(s: pd.Series) -> bool:
    return is_text(s) or isinstance(s.dtype, pd.CategoricalDtype) or pd.api.types.is_bool_dtype(s)


def validate_extension(filename: str) -> Optional[str]:
    ext = Path(filename).suffix.lower()
    if ext not in config.SUPPORTED_EXTENSIONS:
        return (f"Unsupported file type '{ext or filename}'. Supported: "
                + ", ".join(sorted(e.lstrip('.') for e in config.SUPPORTED_EXTENSIONS)))
    return None


def validate_dataframe(df: Optional[pd.DataFrame]) -> Optional[str]:
    if df is None:
        return "No dataset is loaded."
    if df.shape[1] == 0:
        return "The dataset has no columns."
    if df.shape[0] == 0:
        return "The dataset has no rows."
    return None


def missing_columns(df: pd.DataFrame, cols: Iterable[Optional[str]]) -> list[str]:
    return [c for c in cols if c and c not in df.columns]
