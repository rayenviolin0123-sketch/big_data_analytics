"""Data-cleaning operations. Every function returns a NEW DataFrame (inputs are never mutated)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from utils.validators import DATE_RE, is_datetime, is_numeric, is_text

MISSING_STRATEGIES = ["Remove", "Mean", "Median", "Mode", "Forward Fill", "Backward Fill", "Custom Value"]
DTYPE_LABELS = ["Integer", "Float", "String", "Boolean", "Date", "Datetime", "Category"]
OUTLIER_METHODS = ["IQR", "Z-Score"]
OUTLIER_ACTIONS = ["Cap (winsorize)", "Remove rows", "Flag only"]
_BOOL_TOKENS = {"true", "false", "yes", "no", "y", "n", "t", "f"}
_BOOL_MAP = {"true": True, "false": False, "yes": True, "no": False, "y": True, "n": False,
             "t": True, "f": False, "1": True, "0": False}


# ---------------------------------------------------------------- type detection
def detect_dtype(s: pd.Series, sample_size: int = 2000) -> str:
    """Return one of DTYPE_LABELS describing what the column *contains*."""
    if pd.api.types.is_bool_dtype(s):
        return "Boolean"
    if isinstance(s.dtype, pd.CategoricalDtype):
        return "Category"
    if is_datetime(s):
        sample = s.dropna().head(sample_size)
        if sample.empty:
            return "Datetime"
        return "Date" if (sample.dt.normalize() == sample).all() else "Datetime"
    if pd.api.types.is_integer_dtype(s):
        return "Integer"
    if pd.api.types.is_float_dtype(s):
        sample = s.dropna().head(sample_size)
        if len(sample) and np.isfinite(sample).all() and (sample == np.floor(sample)).all():
            return "Integer"
        return "Float"
    if is_text(s):
        sample = s.dropna().head(sample_size).astype(str).str.strip()
        sample = sample[sample != ""]
        if sample.empty:
            return "String"
        low = sample.str.lower()
        if low.nunique() <= 2 and low.isin(_BOOL_TOKENS).all():
            return "Boolean"
        num = pd.to_numeric(sample, errors="coerce")
        if num.notna().mean() >= 0.95:
            nn = num.dropna()
            return "Integer" if (nn == np.floor(nn)).all() else "Float"
        if sample.str.match(DATE_RE).mean() >= 0.9:
            parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
            if parsed.notna().mean() >= 0.9:
                p = parsed.dropna()
                return "Date" if (p.dt.normalize() == p).all() else "Datetime"
        n, u = len(s), s.nunique()
        if u <= 50 or u / max(n, 1) < 0.05:
            return "Category"
    return "String"


def suggested_type(s: pd.Series) -> str:
    """Non-empty only when a text column really holds numbers / dates / booleans."""
    if not is_text(s):
        return ""
    d = detect_dtype(s)
    return d if d in ("Integer", "Float", "Date", "Datetime", "Boolean") else ""


def dtype_report(df: pd.DataFrame, sample_rows: int = 100_000) -> pd.DataFrame:
    sample = df if len(df) <= sample_rows else df.sample(sample_rows, random_state=1)
    rows = []
    for c in df.columns:
        sug = suggested_type(sample[c])
        rows.append({
            "Column": c, "Stored dtype": str(df[c].dtype), "Detected type": detect_dtype(sample[c]),
            "Unique": int(sample[c].nunique()), "Missing": int(df[c].isna().sum()),
            "Status": f"⚠ convert to {sug}" if sug else "✔ OK",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- type conversion
def convert_dtype(df: pd.DataFrame, column: str, target: str) -> Tuple[pd.DataFrame, str]:
    if column not in df.columns:
        return df, f"⚠️ Column '{column}' no longer exists."
    out = df.copy()
    s = out[column]
    na_before = int(s.isna().sum())
    try:
        if target == "String":
            out[column] = s.astype("string")
        elif target == "Integer":
            conv = pd.to_numeric(s, errors="coerce")
            out[column] = conv.round().astype("Int64")
        elif target == "Float":
            out[column] = pd.to_numeric(s, errors="coerce").astype("float64")
        elif target in ("Date", "Datetime"):
            conv = pd.to_datetime(s, errors="coerce", format="mixed")
            out[column] = conv.dt.normalize() if target == "Date" else conv
        elif target == "Category":
            out[column] = s.astype("category")
        elif target == "Boolean":
            if pd.api.types.is_bool_dtype(s):
                out[column] = s
            else:
                mapped = s.astype("string").str.strip().str.lower().map(_BOOL_MAP)
                out[column] = mapped.astype("boolean")
        else:
            return df, f"⚠️ Unknown target type '{target}'."
    except Exception as exc:  # noqa: BLE001 - surface any conversion failure as a message
        return df, f"⚠️ Could not convert '{column}' to {target}: {exc}"
    failed = int(out[column].isna().sum()) - na_before
    msg = f"Converted '{column}': {s.dtype} → {out[column].dtype}."
    if failed > 0:
        msg += f" ⚠️ {failed:,} value(s) could not be converted and became missing."
    return out, msg


def auto_convert_suggested(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    out, done = df, []
    for c in df.columns:
        sug = suggested_type(df[c].head(5000))
        if sug:
            out, _ = convert_dtype(out, c, sug)
            done.append(f"{c} → {sug}")
    return out, done


def auto_parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Used at load time: turn text columns that clearly contain dates into datetimes."""
    out = df
    for c in df.columns:
        if is_text(df[c]) and suggested_type(df[c]) in ("Date", "Datetime"):
            parsed = pd.to_datetime(df[c], errors="coerce", format="mixed")
            if parsed.notna().sum() >= 0.9 * df[c].notna().sum():
                if out is df:
                    out = df.copy()
                out[c] = parsed
    return out


# ---------------------------------------------------------------- missing values
def missing_summary(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    miss = df.isna().sum()
    out = pd.DataFrame({"Column": miss.index, "Missing": miss.values,
                        "Missing %": (miss.values / n * 100) if n else 0.0})
    return out[out["Missing"] > 0].sort_values("Missing", ascending=False).reset_index(drop=True)


def apply_missing(df: pd.DataFrame, column: str, strategy: str,
                  custom_value: Optional[str] = None) -> Tuple[pd.DataFrame, str]:
    if column not in df.columns:
        return df, f"⚠️ Column '{column}' no longer exists."
    s = df[column]
    before = int(s.isna().sum())
    if before == 0:
        return df, f"'{column}' has no missing values."
    out = df.copy()
    if strategy == "Remove":
        out = out.dropna(subset=[column])
    elif strategy in ("Mean", "Median"):
        if not is_numeric(s):
            return df, f"⚠️ '{column}' is not numeric, so the {strategy.lower()} cannot be computed. Try Mode."
        out[column] = s.fillna(s.mean() if strategy == "Mean" else s.median())
    elif strategy == "Mode":
        mode = s.mode(dropna=True)
        if mode.empty:
            return df, f"⚠️ '{column}' has no mode (all values are missing)."
        out[column] = s.fillna(mode.iloc[0])
    elif strategy == "Forward Fill":
        out[column] = s.ffill()
    elif strategy == "Backward Fill":
        out[column] = s.bfill()
    elif strategy == "Custom Value":
        if custom_value is None or str(custom_value).strip() == "":
            return df, "⚠️ Please enter a custom value."
        try:
            if is_numeric(s):
                val = float(custom_value)
                if pd.api.types.is_integer_dtype(s) and val.is_integer():
                    val = int(val)
            elif is_datetime(s):
                val = pd.Timestamp(custom_value)
            elif pd.api.types.is_bool_dtype(s):
                val = _BOOL_MAP[str(custom_value).strip().lower()]
            else:
                val = str(custom_value)
            if isinstance(s.dtype, pd.CategoricalDtype) and val not in s.cat.categories:
                out[column] = s.cat.add_categories([val]).fillna(val)
            else:
                out[column] = s.fillna(val)
        except (ValueError, KeyError):
            return df, f"⚠️ '{custom_value}' is not a valid value for the {s.dtype} column '{column}'."
    else:
        return df, f"⚠️ Unknown strategy '{strategy}'."
    after = int(out[column].isna().sum())
    removed = len(df) - len(out)
    return out, f"{strategy} on '{column}': {before - after:,} missing value(s) handled, {removed:,} row(s) removed."


def fill_missing_auto(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Numeric → median, text/category → mode, dates → forward/backward fill."""
    out = df.copy()
    filled = 0
    for c in df.columns:
        s = out[c]
        n = int(s.isna().sum())
        if n == 0 or n == len(s):
            continue
        if is_numeric(s):
            out[c] = s.fillna(s.median())
        elif is_datetime(s):
            out[c] = s.ffill().bfill()
        else:
            mode = s.mode(dropna=True)
            if mode.empty:
                continue
            if isinstance(s.dtype, pd.CategoricalDtype):
                out[c] = s.fillna(mode.iloc[0])
            else:
                out[c] = s.fillna(mode.iloc[0])
        filled += n - int(out[c].isna().sum())
    return out, filled


# ---------------------------------------------------------------- duplicates
def duplicate_count(df: pd.DataFrame, subset: Optional[List[str]] = None) -> int:
    return int(df.duplicated(subset=subset or None).sum())


def drop_duplicates(df: pd.DataFrame, subset: Optional[List[str]] = None) -> Tuple[pd.DataFrame, int]:
    out = df.drop_duplicates(subset=subset or None).reset_index(drop=True)
    return out, len(df) - len(out)


# ---------------------------------------------------------------- text standardisation
def _clean_text(s: pd.Series) -> pd.Series:
    if pd.api.types.is_object_dtype(s):
        is_str = s.map(lambda v: isinstance(v, str))
        out = s.copy()
        if is_str.any():
            out[is_str] = s[is_str].str.strip().str.replace(r"\s+", " ", regex=True)
        return out
    return s.str.strip().str.replace(r"\s+", " ", regex=True)


def standardize_text(df: pd.DataFrame, blank_to_nan: bool = True) -> Tuple[pd.DataFrame, int]:
    """Trim / collapse whitespace in text columns; blank strings become missing."""
    out = df.copy()
    changed = 0
    for c in df.columns:
        s = df[c]
        if not is_text(s):
            continue
        new = _clean_text(s)
        if blank_to_nan:
            new = new.where(new != "", np.nan) if pd.api.types.is_object_dtype(new) else new.replace("", pd.NA)
        diff = (new.astype(str) != s.astype(str)) & s.notna()
        changed += int(diff.sum())
        out[c] = new
    return out, changed


# ---------------------------------------------------------------- outliers
def outlier_bounds(s: pd.Series, method: str = "IQR", z: float = 3.0, k: float = 1.5) -> Optional[Tuple[float, float]]:
    x = pd.to_numeric(s, errors="coerce").astype("float64")
    x = x[np.isfinite(x)]
    if x.empty:
        return None
    if method == "IQR":
        q1, q3 = x.quantile(0.25), x.quantile(0.75)
        iqr = q3 - q1
        return float(q1 - k * iqr), float(q3 + k * iqr)
    mu, sd = float(x.mean()), float(x.std())
    if not sd or np.isnan(sd):
        return mu, mu
    return mu - z * sd, mu + z * sd


def outlier_mask(s: pd.Series, method: str = "IQR", z: float = 3.0) -> pd.Series:
    b = outlier_bounds(s, method, z)
    if b is None:
        return pd.Series(False, index=s.index)
    x = pd.to_numeric(s, errors="coerce")
    return ((x < b[0]) | (x > b[1])).fillna(False)


def count_outliers(df: pd.DataFrame, method: str = "IQR", z: float = 3.0) -> Dict[str, int]:
    return {c: int(outlier_mask(df[c], method, z).sum()) for c in df.columns if is_numeric(df[c])}


def handle_outliers(df: pd.DataFrame, column: str, method: str, action: str,
                    z: float = 3.0) -> Tuple[pd.DataFrame, str]:
    if column not in df.columns or not is_numeric(df[column]):
        return df, f"⚠️ Unable to treat outliers: '{column}' is not a numeric column."
    bounds = outlier_bounds(df[column], method, z)
    if bounds is None:
        return df, f"⚠️ '{column}' contains no finite numeric values."
    mask = outlier_mask(df[column], method, z)
    n = int(mask.sum())
    if n == 0:
        return df, f"No {method} outliers found in '{column}'."
    out = df.copy()
    if action == "Remove rows":
        out = out[~mask].reset_index(drop=True)
        return out, f"Removed {n:,} outlier row(s) from '{column}' ({method})."
    if action == "Cap (winsorize)":
        s = out[column]
        capped = s.clip(lower=bounds[0], upper=bounds[1])
        if pd.api.types.is_integer_dtype(s):
            capped = capped.round().astype(s.dtype)
        out[column] = capped
        return out, f"Capped {n:,} outlier(s) in '{column}' to [{bounds[0]:,.2f}, {bounds[1]:,.2f}]."
    out[f"{column}_is_outlier"] = mask.values
    return out, f"Flagged {n:,} outlier(s) in new column '{column}_is_outlier'."
