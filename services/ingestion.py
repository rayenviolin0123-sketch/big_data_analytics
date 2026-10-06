"""Data ingestion: CSV / Excel / JSON / Parquet with streaming and sampling for big files.

Reader priority for CSV: Polars (lazy scan) → DuckDB → pandas (chunked). Whatever engine runs,
the *exact* number of source records is counted; if it exceeds ``max_rows`` the in-memory working
set is a uniform systematic/reservoir sample so the app stays responsive.
"""
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import config
from services import cleaning
from utils.helpers import HAS_DUCKDB, HAS_POLARS, HAS_PYARROW, sanitize_filename


@dataclass
class LoadResult:
    df: Optional[pd.DataFrame]
    meta: dict
    error: Optional[str] = None


# ------------------------------------------------------------------ CSV readers
def _sniff_delimiter(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(65536)
        return csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
    except (csv.Error, OSError):
        return "\t" if path.suffix.lower() == ".tsv" else ","


def _csv_polars(path: Path, sep: str, max_rows: int, progress=None):
    import polars as pl
    lf = pl.scan_csv(str(path), separator=sep, infer_schema_length=10_000, ignore_errors=True,
                     try_parse_dates=True, encoding="utf8-lossy")
    total = int(lf.select(pl.len()).collect().item())
    if total <= max_rows:
        out = lf.collect()
    else:
        k = math.ceil(total / max_rows)
        out = lf.with_row_index("__row").filter((pl.col("__row") % k) == 0).drop("__row").collect()
    return out.to_pandas(), total


def _csv_duckdb(path: Path, sep: str, max_rows: int, progress=None):
    import duckdb
    p = str(path).replace("'", "''")
    d = sep.replace("'", "''")
    src = f"read_csv_auto('{p}', delim='{d}', sample_size=20000, ignore_errors=true)"
    con = duckdb.connect()
    try:
        total = int(con.execute(f"SELECT count(*) FROM {src}").fetchone()[0])
        if total <= max_rows:
            df = con.execute(f"SELECT * FROM {src}").df()
        else:
            df = con.execute(f"SELECT * FROM {src} USING SAMPLE reservoir({int(max_rows)} ROWS) REPEATABLE (42)").df()
    finally:
        con.close()
    return df, total


def _csv_pandas(path: Path, sep: str, max_rows: int, progress=None):
    """Chunked read with adaptive uniform sampling: memory stays ≈ max_rows regardless of file size."""
    rng = np.random.default_rng(42)
    keep: list[pd.DataFrame] = []
    kept = total = 0
    rate = 1.0
    reader = pd.read_csv(path, sep=sep, chunksize=config.CHUNK_SIZE, encoding_errors="replace",
                         on_bad_lines="skip")
    for chunk in reader:
        total += len(chunk)
        part = chunk if rate >= 1.0 else chunk[rng.random(len(chunk)) < rate]
        keep.append(part)
        kept += len(part)
        while kept > max_rows:           # halve the sampling rate and thin what we already hold
            rate /= 2
            keep = [p[rng.random(len(p)) < 0.5] for p in keep]
            kept = sum(len(p) for p in keep)
        if progress:
            progress(total)
    if not keep:
        raise pd.errors.EmptyDataError("No columns to parse from file")
    return pd.concat(keep, ignore_index=True), total


def _csv_readers() -> list[tuple[str, Callable]]:
    readers = []
    if HAS_POLARS and HAS_PYARROW:
        readers.append(("Polars (lazy scan)", _csv_polars))
    if HAS_DUCKDB:
        readers.append(("DuckDB", _csv_duckdb))
    readers.append(("pandas (chunked)", _csv_pandas))
    return readers


# ------------------------------------------------------------------ other formats
def _read_parquet(path: Path, max_rows: int):
    if not HAS_PYARROW:
        raise ImportError("Reading Parquet requires the 'pyarrow' package (pip install pyarrow).")
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    total = int(pf.metadata.num_rows)
    if total <= max_rows:
        return pf.read().to_pandas(), total
    k = math.ceil(total / max_rows)
    parts, offset = [], 0
    for batch in pf.iter_batches(batch_size=config.CHUNK_SIZE):
        d = batch.to_pandas()
        idx = np.arange(offset, offset + len(d))
        parts.append(d[idx % k == 0])
        offset += len(d)
    return pd.concat(parts, ignore_index=True), total


def _read_json(path: Path):
    ext = path.suffix.lower()
    try:
        df = pd.read_json(path, lines=(ext == ".jsonl"))
    except ValueError:
        try:
            df = pd.read_json(path, lines=True)
        except ValueError:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                lists = [v for v in obj.values() if isinstance(v, list)]
                obj = lists[0] if lists else [obj]
            df = pd.json_normalize(obj)
    return df


def _read_excel(path: Path):
    return pd.read_excel(path, engine="openpyxl" if path.suffix.lower() == ".xlsx" else None)


def _systematic_sample(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if len(df) <= max_rows:
        return df
    k = math.ceil(len(df) / max_rows)
    return df.iloc[::k].reset_index(drop=True)


# ------------------------------------------------------------------ public API
def save_upload(name: str, content: bytes) -> Path:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RAW_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{sanitize_filename(name)}"
    path.write_bytes(content)
    return path


def load_dataset(path: str | Path, max_rows: Optional[int] = None, display_name: Optional[str] = None,
                 progress: Optional[Callable[[int], None]] = None) -> LoadResult:
    """Load a dataset from disk. Never raises: failures come back as ``LoadResult.error``."""
    max_rows = int(max_rows or config.MAX_ROWS_IN_MEMORY)
    path = Path(str(path).strip().strip('"'))
    if not path.exists() or not path.is_file():
        return LoadResult(None, {}, f"File not found: {path}")
    ext = path.suffix.lower()
    if ext not in config.SUPPORTED_EXTENSIONS:
        return LoadResult(None, {}, f"Unsupported file type '{ext}'.")
    size = path.stat().st_size
    if size == 0:
        return LoadResult(None, {}, "The file is empty (0 bytes).")

    t0 = time.perf_counter()
    engine = "pandas"
    try:
        if ext in config.CSV_EXTENSIONS:
            sep = _sniff_delimiter(path)
            df, total, last_err = None, 0, None
            for name, fn in _csv_readers():
                try:
                    df, total = fn(path, sep, max_rows, progress)
                    engine = name
                    break
                except pd.errors.EmptyDataError:
                    raise
                except Exception as exc:  # noqa: BLE001 - fall through to the next engine
                    last_err = exc
            if df is None:
                raise last_err or ValueError("could not parse CSV")
        elif ext == ".parquet":
            df, total = _read_parquet(path, max_rows)
            engine = "PyArrow"
        elif ext in (".json", ".jsonl"):
            df = _read_json(path)
            total = len(df)
            df = _systematic_sample(df, max_rows)
            engine = "pandas (JSON)"
        else:
            df = _read_excel(path)
            total = len(df)
            df = _systematic_sample(df, max_rows)
            engine = "openpyxl (Excel)"
    except pd.errors.EmptyDataError:
        return LoadResult(None, {}, "The file contains no data.")
    except MemoryError:
        return LoadResult(None, {}, "Not enough memory to load this file. Lower the row limit or convert it to Parquet.")
    except ImportError as exc:
        return LoadResult(None, {}, f"A required library is missing: {exc}")
    except Exception as exc:  # noqa: BLE001
        return LoadResult(None, {}, f"The file could not be read — it may be corrupted or malformed. ({exc})")

    if df is None or df.shape[1] == 0 or len(df) == 0:
        return LoadResult(None, {}, "The dataset is empty (no rows or no columns).")

    df = _normalise_columns(df)
    df = cleaning.auto_parse_dates(df)
    seconds = time.perf_counter() - t0
    meta = {
        "name": display_name or path.name, "path": str(path), "format": ext.lstrip(".").upper(),
        "size_bytes": size, "total_rows": int(total), "total_cols": int(df.shape[1]),
        "analysed_rows": int(len(df)), "sampled": int(total) > len(df),
        "load_seconds": seconds, "engine": engine, "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    return LoadResult(df, meta)


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols, seen = [], {}
    for c in df.columns:
        name = str(c).strip() or "column"
        seen[name] = seen.get(name, 0) + 1
        cols.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    df = df.copy() if list(df.columns) != cols else df
    df.columns = cols
    return df


def from_dataframe(df: pd.DataFrame, name: str, load_seconds: float = 0.0, engine: str = "in-memory") -> LoadResult:
    meta = {
        "name": name, "path": "", "format": "GENERATED", "size_bytes": int(df.memory_usage(deep=False).sum()),
        "total_rows": int(len(df)), "total_cols": int(df.shape[1]), "analysed_rows": int(len(df)),
        "sampled": False, "load_seconds": load_seconds, "engine": engine,
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    return LoadResult(df, meta)


def write_parquet(df: pd.DataFrame, name: str) -> Optional[Path]:
    """Persist a DataFrame to data/processed as Snappy Parquet. Returns None if PyArrow is missing."""
    if not HAS_PYARROW:
        return None
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PROCESSED_DIR / f"{Path(sanitize_filename(name)).stem}.parquet"
    try:
        df.to_parquet(path, index=False, compression="snappy")
    except Exception:  # noqa: BLE001 - mixed-type object columns: stringify and retry
        fixed = df.copy()
        for c in fixed.columns:
            if pd.api.types.is_object_dtype(fixed[c]):
                fixed[c] = fixed[c].astype("string")
        try:
            fixed.to_parquet(path, index=False, compression="snappy")
        except Exception:  # noqa: BLE001
            return None
    return path


# ------------------------------------------------------------------ sample data
def generate_sample(n_rows: int = 100_000, seed: int = 42) -> pd.DataFrame:
    """Synthetic e-commerce transactions with realistic flaws (missing, duplicates, outliers, messy text)."""
    rng = np.random.default_rng(seed)
    n = int(n_rows)
    span = int(3 * 365 * 24 * 3600)
    offsets = (rng.beta(1.4, 1.0, n) * span).astype("int64")          # growth: more orders later
    ts = np.datetime64("2023-01-01T00:00:00") + offsets.astype("timedelta64[s]")

    countries = np.array(["United States", "Germany", "France", "United Kingdom", "Spain",
                          "Italy", "Canada", "Brazil", "India", "Japan"])
    country = pd.Series(rng.choice(countries, n, p=[.28, .12, .10, .10, .06, .06, .08, .07, .08, .05]), dtype=object)
    categories = np.array(["Electronics", "Home & Garden", "Fashion", "Sports", "Beauty", "Toys"])
    base_price = np.array([220, 80, 55, 70, 35, 28])
    cat_idx = rng.choice(len(categories), n, p=[.22, .18, .25, .12, .13, .10])
    channel = rng.choice(["Web", "Mobile App", "Marketplace", "Store"], n, p=[.45, .30, .15, .10])
    payment = rng.choice(["Credit Card", "PayPal", "Bank Transfer", "Gift Card"], n, p=[.55, .25, .12, .08])

    unit_price = np.round(base_price[cat_idx] * rng.lognormal(0, 0.45, n), 2)
    quantity = rng.poisson(1.6, n) + 1
    discount = rng.choice([0, .05, .10, .20, .30], n, p=[.5, .2, .15, .1, .05])
    revenue = np.round(quantity * unit_price * (1 - discount), 2)
    hit = rng.choice(n, max(1, int(n * .001)), replace=False)
    revenue[hit] = np.round(revenue[hit] * 12, 2)                      # extreme outliers

    age = np.clip(np.round(rng.normal(38, 12, n)), 18, 85).astype("float64")
    rating = np.clip(np.round(rng.normal(4.1, .9, n) - discount * 1.5), 1, 5).astype("float64")
    delivery = (rng.poisson(4, n) + 1).astype("float64")
    delivery[rng.choice(n, max(1, int(n * .002)), replace=False)] += 45
    returned = rng.random(n) < (0.03 + 0.12 * (rating <= 2))

    age[rng.choice(n, int(n * .03), replace=False)] = np.nan
    rating[rng.choice(n, int(n * .08), replace=False)] = np.nan
    messy = rng.choice(n, int(n * .004), replace=False)
    half = len(messy) // 2
    country.iloc[messy[:half]] = country.iloc[messy[:half]].str.lower()
    country.iloc[messy[half:]] = country.iloc[messy[half:]] + " "

    df = pd.DataFrame({
        "transaction_id": np.arange(1, n + 1) + 10_000_000,
        "order_ts": pd.to_datetime(ts),
        "customer_id": rng.integers(1, max(10, n // 8), n),
        "country": country,
        "category": categories[cat_idx],
        "channel": channel,
        "payment_method": payment,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount": discount,
        "revenue": revenue,
        "customer_age": age,
        "rating": rating,
        "delivery_days": delivery,
        "is_returned": returned,
    })
    dup = df.sample(max(1, int(n * .003)), random_state=seed)           # exact duplicate records
    df = pd.concat([df, dup], ignore_index=True).sort_values("order_ts", kind="stable").reset_index(drop=True)
    return df
