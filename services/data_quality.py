"""Data-quality assessment across five dimensions plus a global 0-100 score.

Dimension definitions (documented so the score is explainable):
  Completeness  share of non-missing cells
  Uniqueness    share of rows that are not exact duplicates
  Validity      share of values that conform to the column's evident type
                (e.g. a mostly-numeric text column containing 'N/A', infinities)
  Consistency   share of text values free of case / whitespace variants ('France', 'france ')
                and of mixed Python types inside one column
  Accuracy      share of numeric values NOT beyond 3×IQR fences (a proxy: extreme values
                are *potentially* wrong, not necessarily wrong)
Text-based checks run on a sample of ``config.ANALYSIS_SAMPLE`` rows and are scaled up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import numpy as np
import pandas as pd

import config
from services import cleaning
from utils.validators import DATE_RE, is_numeric, is_text

DIMENSIONS = list(config.QUALITY_WEIGHTS)


@dataclass
class QualityReport:
    score: float
    label: str
    dimensions: Dict[str, float]
    issues: pd.DataFrame
    columns: pd.DataFrame
    counts: Dict[str, int] = field(default_factory=dict)
    sampled: bool = False


def label_for(score: float) -> str:
    return "Excellent" if score >= 90 else "Good" if score >= 75 else "Fair" if score >= 60 else "Poor"


def _status(pct: float, warn: float = 1.0, crit: float = 5.0) -> str:
    return "Good" if pct < warn else "Warning" if pct < crit else "Critical"


def _text_validity(nn: pd.Series) -> int:
    """Count values that violate the evident type of a text column (0 if it's free text)."""
    st = nn.astype(str).str.strip()
    num = pd.to_numeric(st, errors="coerce")
    if num.notna().mean() >= 0.8:
        return int(num.isna().sum())
    if st.str.match(DATE_RE).mean() >= 0.8:
        return int(pd.to_datetime(st, errors="coerce", format="mixed").isna().sum())
    return 0


def _text_inconsistency(nn: pd.Series) -> int:
    """Count values that are case/whitespace variants of a more common spelling, or of a minority python type."""
    if nn.empty:
        return 0
    bad = 0
    as_str = nn.astype(str)
    if as_str.nunique() <= 5000:
        vc = as_str.value_counts()
        v = pd.DataFrame({"val": vc.index.astype(str), "cnt": vc.values})
        v["norm"] = v["val"].str.strip().str.replace(r"\s+", " ", regex=True).str.casefold()
        v["top"] = v.groupby("norm")["cnt"].rank(method="first", ascending=False) == 1
        v["ws"] = v["val"] != v["val"].str.strip()
        bad += int(v.loc[(~v["top"]) | v["ws"], "cnt"].sum())
    if pd.api.types.is_object_dtype(nn):
        types = nn.map(lambda x: type(x).__name__).value_counts()
        if len(types) > 1:
            bad = max(bad, int(types.sum() - types.iloc[0]))
    return min(bad, len(nn))


def assess(df: pd.DataFrame) -> QualityReport:
    n_rows, n_cols = df.shape
    if n_rows == 0 or n_cols == 0:
        return QualityReport(0.0, "No data", {d: 0.0 for d in DIMENSIONS}, pd.DataFrame(), pd.DataFrame())

    sample = df if n_rows <= config.ANALYSIS_SAMPLE else df.sample(config.ANALYSIS_SAMPLE, random_state=42)
    scale = n_rows / len(sample)
    sampled = len(sample) < n_rows

    miss = df.isna().sum()
    total_cells = n_rows * n_cols
    missing_cells = int(miss.sum())
    empty_cols = [c for c in df.columns if miss[c] == n_rows]
    dup_rows = int(df.duplicated().sum())

    invalid_total = nonnull_checked = 0
    incons_total = text_checked = 0
    numeric_cells = extreme_total = outlier_total = 0
    incorrect_types: list[str] = []
    col_rows = []

    for c in df.columns:
        full, s = df[c], sample[c]
        invalid = outliers = 0
        incons = 0
        if is_numeric(full):
            x = pd.to_numeric(full, errors="coerce").astype("float64")
            invalid = int(np.isinf(x).sum())
            fin = x[np.isfinite(x)]
            numeric_cells += len(fin)
            if len(fin) >= 4:
                q1, q3 = fin.quantile(0.25), fin.quantile(0.75)
                iqr = q3 - q1
                outliers = int(((fin < q1 - 1.5 * iqr) | (fin > q3 + 1.5 * iqr)).sum())
                extreme_total += int(((fin < q1 - 3 * iqr) | (fin > q3 + 3 * iqr)).sum())
            outlier_total += outliers
            nonnull_checked += int(x.notna().sum())
        elif is_text(full) or isinstance(full.dtype, pd.CategoricalDtype):
            nn = s.dropna()
            if not nn.empty:
                if is_text(full):
                    invalid = int(round(_text_validity(nn) * scale))
                    if cleaning.suggested_type(nn.head(2000)):
                        incorrect_types.append(c)
                incons = int(round(_text_inconsistency(nn) * scale))
                text_checked += int(full.notna().sum())
                nonnull_checked += int(full.notna().sum())
        else:
            nonnull_checked += int(full.notna().sum())
        invalid_total += invalid
        incons_total += incons
        n_missing = int(miss[c])
        col_rows.append({
            "Column": c, "Detected type": cleaning.detect_dtype(s), "Missing": n_missing,
            "Missing %": n_missing / n_rows * 100, "Unique (est.)": int(s.nunique()),
            "Invalid": invalid, "Inconsistent": incons, "Outliers": outliers,
        })

    completeness = 100 * (1 - missing_cells / total_cells)
    uniqueness = 100 * (1 - dup_rows / n_rows)
    validity = 100 * (1 - invalid_total / nonnull_checked) if nonnull_checked else 100.0
    consistency = 100 * (1 - incons_total / text_checked) if text_checked else 100.0
    accuracy = 100 * (1 - extreme_total / numeric_cells) if numeric_cells else 100.0
    dims = {k: float(np.clip(v, 0, 100)) for k, v in
            {"Completeness": completeness, "Accuracy": accuracy, "Consistency": consistency,
             "Uniqueness": uniqueness, "Validity": validity}.items()}
    score = round(sum(dims[k] * w for k, w in config.QUALITY_WEIGHTS.items()), 1)

    miss_pct = missing_cells / total_cells * 100
    dup_pct = dup_rows / n_rows * 100
    inv_pct = invalid_total / nonnull_checked * 100 if nonnull_checked else 0.0
    out_pct = outlier_total / numeric_cells * 100 if numeric_cells else 0.0
    issues = pd.DataFrame([
        {"Check": "Missing values", "Count": missing_cells, "Percent": miss_pct, "Status": _status(miss_pct)},
        {"Check": "Duplicate records", "Count": dup_rows, "Percent": dup_pct, "Status": _status(dup_pct, .5, 3)},
        {"Check": "Invalid values", "Count": invalid_total, "Percent": inv_pct, "Status": _status(inv_pct, .1, 2)},
        {"Check": "Empty columns", "Count": len(empty_cols), "Percent": len(empty_cols) / n_cols * 100,
         "Status": "Good" if not empty_cols else "Critical"},
        {"Check": "Incorrect types", "Count": len(incorrect_types), "Percent": len(incorrect_types) / n_cols * 100,
         "Status": "Good" if not incorrect_types else "Warning"},
        {"Check": "Outliers (IQR 1.5×)", "Count": outlier_total, "Percent": out_pct, "Status": _status(out_pct, 1, 5)},
    ])
    counts = {"missing_cells": missing_cells, "duplicates": dup_rows, "invalid": invalid_total,
              "empty_columns": len(empty_cols), "incorrect_types": len(incorrect_types),
              "outliers": outlier_total, "rows": n_rows, "cols": n_cols,
              "missing_pct": miss_pct, "duplicate_pct": dup_pct}
    return QualityReport(score, label_for(score), dims, issues, pd.DataFrame(col_rows), counts, sampled)
