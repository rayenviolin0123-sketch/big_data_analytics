"""Analytics: summaries, temporal trends, correlations, aggregation, SQL, insights."""
from __future__ import annotations

import re
import sqlite3
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

import config
from services import cleaning, data_quality
from utils.helpers import HAS_DUCKDB
from utils.validators import is_categorical_like, is_datetime, is_numeric

AGG = config.AGGREGATIONS
FREQ = {"Daily": "D", "Weekly": "W", "Monthly": "MS", "Yearly": "YS"}


# ------------------------------------------------------------------ column groups
def numeric_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if is_numeric(df[c])]


def datetime_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if is_datetime(df[c])]


def categorical_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if is_categorical_like(df[c])]


def low_cardinality_cols(df: pd.DataFrame, max_unique: int = 50) -> List[str]:
    sample = df if len(df) <= 50_000 else df.sample(50_000, random_state=3)
    return [c for c in categorical_cols(df) if 1 < sample[c].nunique() <= max_unique]


def measure_columns(df: pd.DataFrame) -> List[str]:
    """Numeric columns that look like measures (not ids / constants)."""
    out = []
    for c in numeric_cols(df):
        s = df[c].dropna()
        if s.empty or s.nunique() <= 1:
            continue
        if pd.api.types.is_integer_dtype(df[c]) and s.nunique() / len(s) > 0.9 and ("id" in c.lower() or s.is_monotonic_increasing):
            continue
        out.append(c)
    return out


def pick_measure(df: pd.DataFrame) -> Optional[str]:
    cols = measure_columns(df)
    for key in ("revenue", "sales", "amount", "total", "profit", "price", "cost", "value"):
        for c in cols:
            if key in c.lower():
                return c
    return cols[0] if cols else None


# ------------------------------------------------------------------ summaries
def numeric_summary(df: pd.DataFrame, cols: Optional[List[str]] = None) -> pd.DataFrame:
    rows = []
    for c in cols or numeric_cols(df):
        s = pd.to_numeric(df[c], errors="coerce").astype("float64")
        s = s[np.isfinite(s)]
        if s.empty:
            continue
        q = s.quantile([.01, .05, .25, .5, .75, .95, .99])
        rows.append({
            "Column": c, "Count": int(s.count()), "Mean": s.mean(), "Median": q[.5], "Std Dev": s.std(),
            "Variance": s.var(), "Min": s.min(), "P1": q[.01], "P5": q[.05], "Q1": q[.25], "Q3": q[.75],
            "P95": q[.95], "P99": q[.99], "Max": s.max(), "IQR": q[.75] - q[.25],
            "Skew": s.skew(), "Kurtosis": s.kurt(),
        })
    return pd.DataFrame(rows)


def categorical_summary(df: pd.DataFrame, cols: Optional[List[str]] = None) -> pd.DataFrame:
    rows = []
    for c in cols or [c for c in categorical_cols(df)]:
        s = df[c].dropna()
        if s.empty:
            continue
        vc = s.astype(str).value_counts()
        top3 = vc.head(3).sum() / len(s) * 100
        rows.append({"Column": c, "Unique": int(len(vc)), "Top value": vc.index[0], "Frequency": int(vc.iloc[0]),
                     "Share %": vc.iloc[0] / len(s) * 100, "Top-3 share %": top3})
    return pd.DataFrame(rows)


def top_categories(df: pd.DataFrame, col: str, n: int = 15) -> pd.DataFrame:
    s = df[col].dropna().astype(str)
    vc = s.value_counts().head(n)
    return pd.DataFrame({col: vc.index, "Count": vc.values, "Share %": vc.values / max(len(s), 1) * 100})


def temporal_trends(df: pd.DataFrame, date_col: str, value_col: Optional[str] = None,
                    agg: str = "Sum", freq: str = "Monthly") -> pd.DataFrame:
    """Resample to Daily/Weekly/Monthly/Yearly. Returns columns [date_col, <value>]."""
    cols = [date_col] + ([value_col] if value_col else [])
    d = df[cols].dropna(subset=[date_col])
    if d.empty:
        return pd.DataFrame(columns=[date_col, "Records"])
    d = d.set_index(date_col).sort_index()
    rule = FREQ[freq]
    if not value_col or agg == "Count":
        res = d.resample(rule).size().rename("Records")
    else:
        res = d[value_col].resample(rule).agg(AGG[agg]).rename(f"{agg} of {value_col}")
    return res.reset_index()


# ------------------------------------------------------------------ correlations
def correlation_matrix(df: pd.DataFrame, method: str = "pearson", max_cols: int = 40) -> Tuple[pd.DataFrame, int]:
    cols = [c for c in measure_columns(df)][:max_cols]
    if len(cols) < 2:
        return pd.DataFrame(), 0
    limit = {"pearson": config.ANALYSIS_SAMPLE, "spearman": 100_000, "kendall": 4_000}[method.lower()]
    d = df[cols] if len(df) <= limit else df[cols].sample(limit, random_state=7)
    return d.replace([np.inf, -np.inf], np.nan).corr(method=method.lower()), len(d)


def top_pairs(corr: pd.DataFrame, threshold: float = 0.6, n: int = 10) -> Dict[str, pd.DataFrame]:
    empty = pd.DataFrame(columns=["Variable 1", "Variable 2", "Correlation"])
    if corr.empty:
        return {"positive": empty, "negative": empty}
    mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
    pairs = corr.where(mask).stack().reset_index()
    pairs.columns = ["Variable 1", "Variable 2", "Correlation"]
    return {
        "positive": pairs[pairs["Correlation"] >= threshold].sort_values("Correlation", ascending=False).head(n).reset_index(drop=True),
        "negative": pairs[pairs["Correlation"] <= -threshold].sort_values("Correlation").head(n).reset_index(drop=True),
    }


def describe_strength(r: float) -> str:
    a = abs(r)
    word = "very weak" if a < .2 else "weak" if a < .4 else "moderate" if a < .6 else "strong" if a < .8 else "very strong"
    return f"{word} {'positive' if r > 0 else 'negative'}"


def pair_test(df: pd.DataFrame, a: str, b: str, method: str = "Pearson") -> Optional[dict]:
    d = df[[a, b]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(d) > 200_000:
        d = d.sample(200_000, random_state=5)
    if len(d) < 3 or d[a].nunique() < 2 or d[b].nunique() < 2:
        return None
    fn = {"Pearson": stats.pearsonr, "Spearman": stats.spearmanr, "Kendall": stats.kendalltau}[method]
    r, p = fn(d[a], d[b])
    return {"r": float(r), "p": float(p), "n": int(len(d))}


# ------------------------------------------------------------------ filtering & aggregation
def apply_filters(df: pd.DataFrame, filters: List[dict]) -> pd.DataFrame:
    mask = None
    for f in filters or []:
        c, v = f["col"], f["value"]
        if c not in df.columns:
            continue
        s = df[c]
        if f["kind"] == "range":
            m = s.between(v[0], v[1])
        elif f["kind"] == "date":
            m = (s >= pd.Timestamp(v[0])) & (s < pd.Timestamp(v[1]) + pd.Timedelta(days=1))
        elif f["kind"] == "in":
            if not v:
                continue
            m = s.isin(v)
        else:
            continue
        mask = m if mask is None else (mask & m)
    return df if mask is None else df[mask]


def auto_time_level(s: pd.Series) -> str:
    span = (s.max() - s.min()).days if s.notna().any() else 0
    return "D" if span <= 120 else "W" if span <= 800 else "M" if span <= 3650 else "Y"


def bucket_datetime(s: pd.Series, level: str) -> pd.Series:
    if level == "D":
        return s.dt.floor("D")
    return s.dt.to_period({"W": "W", "M": "M", "Y": "Y"}[level]).dt.to_timestamp()


def limit_categories(df: pd.DataFrame, col: str, n: int) -> pd.DataFrame:
    if df[col].nunique() <= n:
        return df
    keep = df[col].value_counts().nlargest(n).index
    return df[df[col].isin(keep)]


def aggregate(df: pd.DataFrame, keys: List[str], y: Optional[str], agg: str) -> Tuple[pd.DataFrame, str]:
    """Group-by aggregation returning (frame, value_column_name)."""
    func = AGG[agg]
    if func == "count" or not y:
        out = df.groupby(keys, dropna=True, observed=True).size().reset_index(name="Count")
        return out, "Count"
    if y in keys:
        raise ValueError("The Y axis must differ from the X axis / Group By columns.")
    if func not in ("count", "nunique") and not is_numeric(df[y]):
        raise ValueError(f"'{y}' is not numeric, so {agg} cannot be computed. Use Count or Unique Count instead.")
    name = f"{agg} of {y}"
    out = df.groupby(keys, dropna=True, observed=True)[y].agg(func).reset_index().rename(columns={y: name})
    return out, name


# ------------------------------------------------------------------ SQL
_BLOCKED = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|install|load|pragma|call|export)\b", re.I)
_FILE_ACCESS = re.compile(r"(\bread_\w+\s*\(|\bglob\s*\(|\bfrom\s+'|\bfrom\s+\")", re.I)


def run_sql(df: pd.DataFrame, query: str, limit: int = 10_000) -> pd.DataFrame:
    """Run a read-only SQL query against the working data, exposed as table ``dataset``."""
    q = query.strip().rstrip(";").strip()
    if not q:
        raise ValueError("Please enter a SQL query.")
    if not re.match(r"^(with|select|describe|summarize|show)\b", q, re.I):
        raise ValueError("Only read-only queries (SELECT / WITH / DESCRIBE / SUMMARIZE) are allowed.")
    if ";" in q:
        raise ValueError("Please run a single statement at a time.")
    if _BLOCKED.search(q) or _FILE_ACCESS.search(q):
        raise ValueError("This query uses a keyword or file-access function that is not allowed in the console.")
    if HAS_DUCKDB:
        import duckdb
        con = duckdb.connect()
        try:
            con.register("dataset", df)
            res = con.execute(q).df()
        finally:
            con.close()
    else:
        d = df if len(df) <= 500_000 else df.sample(500_000, random_state=1)
        d = d.copy()
        for c in d.columns:
            if is_datetime(d[c]) or isinstance(d[c].dtype, pd.CategoricalDtype):
                d[c] = d[c].astype(str)
            elif str(d[c].dtype) in ("boolean", "string", "Int64"):
                d[c] = d[c].astype(object)
        con = sqlite3.connect(":memory:")
        try:
            d.to_sql("dataset", con, index=False)
            res = pd.read_sql_query(q, con)
        finally:
            con.close()
    return res.head(limit)


# ------------------------------------------------------------------ footprint & diagnostics
def memory_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    sample = df if len(df) <= 50_000 else df.sample(50_000, random_state=2)
    scale = len(df) / len(sample)
    mem = sample.memory_usage(deep=True, index=False) * scale
    out = pd.DataFrame({"Column": mem.index, "Memory (MB)": mem.values / 1024 ** 2,
                        "Stored dtype": [str(df[c].dtype) for c in mem.index]})
    return out.sort_values("Memory (MB)", ascending=False).reset_index(drop=True)


def normality_tests(df: pd.DataFrame, cols: Optional[List[str]] = None, max_n: int = 5000) -> pd.DataFrame:
    rows = []
    for c in cols or measure_columns(df)[:12]:
        s = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(s) < 20 or s.nunique() < 3:
            continue
        s = s.sample(max_n, random_state=11) if len(s) > max_n else s
        stat, p = stats.normaltest(s)
        rows.append({"Column": c, "n tested": len(s), "Skew": stats.skew(s), "Excess kurtosis": stats.kurtosis(s),
                     "p-value": p, "Verdict": "Not normal (p < 0.05)" if p < 0.05 else "No evidence against normality"})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ insights
def _ins(category: str, severity: str, title: str, detail: str, action: str = "") -> dict:
    return {"category": category, "severity": severity, "title": title, "detail": detail, "action": action}


def generate_insights(df: pd.DataFrame, report: Optional[data_quality.QualityReport] = None,
                      threshold: float = 0.6) -> List[dict]:
    """Rule-based insights. 'Significant' is only used when a test was actually run (trend regression)."""
    out: List[dict] = []
    if df.empty:
        return out
    rep = report or data_quality.assess(df)
    c = rep.counts

    # ---- data health
    out.append(_ins("Data health", "success" if rep.score >= 90 else "info" if rep.score >= 75 else "warning",
                    f"Data quality score is {rep.score:.1f}/100 ({rep.label})",
                    "Weakest dimension: " + min(rep.dimensions, key=rep.dimensions.get) +
                    f" ({min(rep.dimensions.values()):.1f}/100)."))
    miss = (df.isna().mean() * 100).sort_values(ascending=False)
    for col, pct in miss[miss > 0].head(3).items():
        out.append(_ins("Data health", "critical" if pct > 20 else "warning" if pct > 5 else "info",
                        f"'{col}' is {pct:.1f}% missing", f"{int(df[col].isna().sum()):,} of {len(df):,} values are empty.",
                        "Impute (median/mode) or exclude this column from models." if pct > 5 else "Consider imputing."))
    if c.get("duplicates"):
        out.append(_ins("Data health", "warning", f"{c['duplicates']:,} duplicate records ({c['duplicate_pct']:.2f}%)",
                        "Exact duplicate rows inflate counts and sums.", "Remove duplicates in Processing → Cleaning tools."))
    if c.get("incorrect_types"):
        out.append(_ins("Data health", "warning", f"{c['incorrect_types']} column(s) stored with the wrong type",
                        "Text columns that actually hold numbers, dates or booleans.", "Convert them in Data Quality or Processing."))
    if c.get("outliers"):
        counts = cleaning.count_outliers(df)
        worst = max(counts, key=counts.get)
        out.append(_ins("Data health", "info", f"{c['outliers']:,} potential outliers (IQR rule)",
                        f"Most are in '{worst}' ({counts[worst]:,}). Outliers are unusual, not necessarily wrong.",
                        "Inspect them before capping or removing."))

    # ---- distributions
    for col in measure_columns(df)[:12]:
        sk = df[col].skew()
        if abs(sk) > 1.5:
            out.append(_ins("Distribution", "info", f"'{col}' is strongly {'right' if sk > 0 else 'left'}-skewed (skew {sk:.2f})",
                            "A few extreme values dominate the mean.", "Prefer the median; consider a log transform for modelling."))
    for col in low_cardinality_cols(df)[:8]:
        vc = df[col].value_counts(normalize=True)
        if len(vc) > 1 and vc.iloc[0] >= 0.5:
            out.append(_ins("Distribution", "info", f"'{vc.index[0]}' dominates '{col}' ({vc.iloc[0] * 100:.1f}%)",
                            "The category is highly imbalanced.", "Account for the imbalance in segmentation or modelling."))

    # ---- relationships (descriptive)
    corr, n_used = correlation_matrix(df)
    tops = top_pairs(corr, threshold, 4)
    for key in ("positive", "negative"):
        for _, r in tops[key].iterrows():
            out.append(_ins("Relationships", "info",
                            f"{r['Variable 1']} ↔ {r['Variable 2']}: {describe_strength(r['Correlation'])} (r = {r['Correlation']:.2f})",
                            f"Pearson correlation on {n_used:,} rows. Correlation does not imply causation."))

    # ---- trend (regression test performed → significance may be stated)
    dts, measure = datetime_cols(df), pick_measure(df)
    if dts and measure:
        monthly = temporal_trends(df, dts[0], measure, "Sum", "Monthly")
        vals = monthly.iloc[:, 1].to_numpy(dtype=float)
        if len(vals) >= 8:
            vals_t = vals[1:-1] if len(vals) >= 10 else vals          # drop partial first/last month
            x = np.arange(len(vals_t))
            res = stats.linregress(x, vals_t)
            first, last = vals_t[:3].mean(), vals_t[-3:].mean()
            chg = (last - first) / abs(first) * 100 if first else np.nan
            direction = "upward" if res.slope > 0 else "downward"
            sig = res.pvalue < 0.05
            out.append(_ins("Trends", "success" if sig and res.slope > 0 else "warning" if sig else "info",
                            (f"Monthly {measure} shows a statistically significant {direction} trend" if sig else
                             f"No statistically significant linear trend in monthly {measure}"),
                            f"Linear regression on {len(vals_t)} monthly totals: slope {res.slope:,.1f}/month, p = {res.pvalue:.3g}. "
                            + (f"Last-3-month average vs first-3: {chg:+.1f}%." if not np.isnan(chg) else "")))
            peak_idx = int(np.argmax(vals))
            peak = monthly.iloc[peak_idx, 0]
            out.append(_ins("Trends", "info", f"Peak month for {measure}: {pd.Timestamp(peak):%B %Y}",
                            f"Highest monthly total: {vals[peak_idx]:,.0f}."))

    # ---- segments
    if measure:
        for col in low_cardinality_cols(df)[:3]:
            g = df.groupby(col, observed=True)[measure].sum().sort_values(ascending=False)
            if len(g) > 2 and g.sum() > 0:
                share = g.iloc[:2].sum() / g.sum() * 100
                out.append(_ins("Segments", "info", f"Top 2 '{col}' values drive {share:.1f}% of total {measure}",
                                f"Leaders: {g.index[0]} ({g.iloc[0] / g.sum() * 100:.1f}%), {g.index[1]} ({g.iloc[1] / g.sum() * 100:.1f}%)."))
    return out
