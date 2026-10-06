"""Optional-dependency detection, timing helpers and Streamlit session-state management.

Session layout (``st.session_state["ds"]``)::

    {"df": working DataFrame, "raw": original DataFrame (never mutated),
     "meta": dict, "version": int, "log": [str], "pipeline": {"stages": {...}, "report": {...}}}

``version`` increases whenever the working data changes; it keys the memo cache so
expensive results (quality score, summaries) are recomputed only when needed.
"""
from __future__ import annotations

import html
import importlib.util
import re
import time
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

import config


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


HAS_POLARS = has_module("polars")
HAS_PYARROW = has_module("pyarrow")
HAS_DUCKDB = has_module("duckdb")
HAS_PYSPARK = has_module("pyspark")
HAS_KAFKA = has_module("kafka")


def engine_status() -> list[dict]:
    return [
        {"name": "Polars", "installed": HAS_POLARS, "role": "Lazy / streaming CSV scans", "optional": False},
        {"name": "PyArrow", "installed": HAS_PYARROW, "role": "Parquet I/O, columnar memory", "optional": False},
        {"name": "DuckDB", "installed": HAS_DUCKDB, "role": "In-process SQL analytics", "optional": False},
        {"name": "PySpark", "installed": HAS_PYSPARK, "role": "Distributed processing (optional)", "optional": True},
        {"name": "Kafka", "installed": HAS_KAFKA, "role": "Streaming ingestion (optional)", "optional": True},
    ]


def esc(value: Any) -> str:
    """HTML-escape anything that ends up inside custom HTML."""
    return html.escape(str(value), quote=True)


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "dataset"


def ensure_dirs() -> None:
    for d in (config.RAW_DIR, config.PROCESSED_DIR, config.SAMPLE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def timed(fn: Callable, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - t0


# --------------------------------------------------------------------------
# session state
# --------------------------------------------------------------------------
STAGES = ["DATA LOADED", "DATA CLEANED", "DATA PROCESSED", "ANALYSIS READY"]


def get_ds() -> Optional[dict]:
    return st.session_state.get("ds")


def has_data() -> bool:
    ds = get_ds()
    return ds is not None and ds["df"] is not None and ds["df"].shape[1] > 0


def get_df() -> Optional[pd.DataFrame]:
    ds = get_ds()
    return ds["df"] if ds else None


def get_meta() -> dict:
    ds = get_ds()
    return ds["meta"] if ds else {}


def set_dataset(df: pd.DataFrame, meta: dict) -> None:
    st.session_state["ds"] = {
        "df": df, "raw": df, "meta": meta, "version": 0, "log": [f"Loaded {meta.get('name', 'dataset')}"],
        "pipeline": {"stages": {s: ("done" if s == STAGES[0] else "pending") for s in STAGES}, "report": None},
    }
    st.session_state["_memo"] = {}


def update_df(df: pd.DataFrame, message: Optional[str] = None) -> None:
    """Replace the working data (cleaning step) and invalidate cached results."""
    ds = st.session_state["ds"]
    ds["df"] = df
    ds["version"] += 1
    if message:
        ds["log"].append(message)
    st.session_state["_memo"] = {}
    # Any manual change means the pipeline stages after "loaded" are stale
    stages = ds["pipeline"]["stages"]
    if message and not message.startswith("Pipeline"):
        for s in STAGES[2:]:
            stages[s] = "pending"
        stages[STAGES[1]] = "done"


def reset_to_original() -> None:
    ds = st.session_state.get("ds")
    if not ds:
        return
    ds["df"] = ds["raw"]
    ds["version"] += 1
    ds["log"].append("Reset to original data")
    ds["pipeline"] = {"stages": {s: ("done" if s == STAGES[0] else "pending") for s in STAGES}, "report": None}
    st.session_state["_memo"] = {}


def get_log() -> list[str]:
    ds = get_ds()
    return ds["log"] if ds else []


def memo(key: str, fn: Callable[[], Any], *extra) -> Any:
    """Cache ``fn()`` for the current dataset version. ``extra`` extends the cache key.
    Never put DataFrames in ``extra`` (use a closure in ``fn`` instead)."""
    ds = get_ds()
    cache = st.session_state.setdefault("_memo", {})
    k = (ds["version"] if ds else -1, key, repr(extra))
    if k not in cache:
        if len(cache) > 150:
            cache.clear()
        cache[k] = fn()
    return cache[k]


def memo_set(key: str, value: Any, *extra) -> None:
    ds = get_ds()
    cache = st.session_state.setdefault("_memo", {})
    cache[(ds["version"] if ds else -1, key, repr(extra))] = value


def total_records() -> int:
    """Exact source record count (differs from len(df) when the data was sampled)."""
    meta, df = get_meta(), get_df()
    if df is None:
        return 0
    if meta.get("sampled") and meta.get("total_rows"):
        return int(meta["total_rows"])
    return len(df)


def goto(page: str) -> None:
    """Button callback: ``st.button(..., on_click=goto, args=("Data Quality",))``."""
    st.session_state["nav"] = page


def require_data() -> Optional[pd.DataFrame]:
    """Return the working frame, or render a friendly empty state and return None."""
    if not has_data():
        st.markdown(
            "<div class='card empty'><div class='empty-icon'>📭</div><h3>No dataset loaded</h3>"
            "<p>Head to <b>Data Ingestion</b> to upload a file, load a Parquet dataset from disk, "
            "or generate a large sample dataset.</p></div>", unsafe_allow_html=True)
        st.button("📥 Go to Data Ingestion", on_click=goto, args=("Data Ingestion",), key="goto_ingestion_empty")
        return None
    return get_df()
