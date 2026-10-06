"""Data ingestion: upload, load from disk, or generate sample data."""
from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

import config
from components.kpi_cards import kpi, render_kpis
from components.metrics import badge, hero
from components.tables import explorer, styled_table
from services import cleaning, ingestion
from utils import helpers, validators
from utils.formatters import fmt_int, human_bytes, human_seconds


def _activate(res: ingestion.LoadResult, to_parquet: bool) -> None:
    """Store a successful load in the session (optionally persisting Parquet)."""
    if to_parquet and helpers.HAS_PYARROW:
        t0 = time.perf_counter()
        pq = ingestion.write_parquet(res.df, Path(res.meta["name"]).stem)
        if pq:
            res.meta["parquet_path"] = str(pq)
            res.meta["parquet_bytes"] = pq.stat().st_size
            res.meta["parquet_seconds"] = time.perf_counter() - t0
    helpers.set_dataset(res.df, res.meta)


def _upload_tab(max_rows: int, to_parquet: bool) -> None:
    st.markdown("<div class='upload-banner'><div class='big'>DROP YOUR DATASET HERE</div>"
                "<div class='small'>CSV · Excel · JSON · Parquet &nbsp;—&nbsp; large files are streamed, not fully loaded</div></div>",
                unsafe_allow_html=True)
    up = st.file_uploader("Upload dataset", type=config.UPLOAD_TYPES, label_visibility="collapsed")
    if up is None:
        st.session_state.pop("_upload_sig", None)
        return
    sig = (up.name, up.size)
    if st.session_state.get("_upload_sig") != sig:
        st.session_state["_upload_sig"] = sig
        err = validators.validate_extension(up.name)
        if err:
            st.session_state["_upload_err"] = (sig, err)
        else:
            with st.spinner(f"Ingesting {up.name} …"):
                path = ingestion.save_upload(up.name, up.getvalue())
                res = ingestion.load_dataset(path, max_rows, display_name=up.name)
            if res.error:
                st.session_state["_upload_err"] = (sig, res.error)
            else:
                st.session_state.pop("_upload_err", None)
                _activate(res, to_parquet)
                st.rerun()
    err = st.session_state.get("_upload_err")
    if err and err[0] == sig:
        st.error(f"⚠️ {err[1]}")


def _path_tab(max_rows: int, to_parquet: bool) -> None:
    st.caption("Best for very large files: the file is read directly from disk (streamed / sampled), "
               "so it never has to pass through the browser upload.")
    path = st.text_input("File path", placeholder=r"C:\data\transactions.csv   or   /data/events.parquet", key="disk_path")
    if st.button("📂 Load from disk", disabled=not path.strip(), key="disk_btn"):
        with st.spinner("Reading file …"):
            res = ingestion.load_dataset(path, max_rows)
        if res.error:
            st.error(f"⚠️ {res.error}")
        else:
            _activate(res, to_parquet)
            st.rerun()


def _sample_tab(to_parquet: bool) -> None:
    st.caption("Synthetic e-commerce transactions with realistic flaws: missing values, duplicates, outliers, "
               "inconsistent text and a growth trend — ideal for exploring every feature.")
    n = st.select_slider("Number of records", [10_000, 100_000, 500_000, 1_000_000, 2_000_000], value=100_000,
                         format_func=lambda v: f"{v:,}", key="sample_n")
    if st.button("✨ Generate sample dataset", type="primary", key="sample_btn"):
        with st.spinner(f"Generating {n:,} records …"):
            t0 = time.perf_counter()
            df = ingestion.generate_sample(n)
            res = ingestion.from_dataframe(df, f"sample_transactions_{n // 1000}k", time.perf_counter() - t0, "NumPy generator")
        _activate(res, to_parquet)
        st.rerun()


def render() -> None:
    st.markdown(hero("📥 Data Ingestion", "Load CSV, Excel, JSON or Parquet — streamed and sampled for big data"),
                unsafe_allow_html=True)
    max_rows = int(st.session_state.get("max_rows", config.MAX_ROWS_IN_MEMORY))
    to_parquet = st.toggle("Convert to Parquet on ingestion", value=helpers.HAS_PYARROW, disabled=not helpers.HAS_PYARROW,
                           help="Columnar, compressed copy saved in data/processed/ (requires PyArrow).")
    t_up, t_disk, t_sample = st.tabs(["⬆️ Upload file", "💽 Load from disk", "✨ Sample dataset"])
    with t_up:
        _upload_tab(max_rows, to_parquet)
    with t_disk:
        _path_tab(max_rows, to_parquet)
    with t_sample:
        _sample_tab(to_parquet)

    if not helpers.has_data():
        return
    df, meta = helpers.get_df(), helpers.get_meta()
    st.markdown("### Dataset information")
    render_kpis([
        kpi("📄", "Filename", meta["name"], meta.get("format", ""), "blue"),
        kpi("💾", "File size", human_bytes(meta.get("size_bytes")), "", "violet"),
        kpi("🧮", "Records", fmt_int(meta["total_rows"]),
            f"{fmt_int(len(df))} analysed (sampled)" if meta.get("sampled") else "all rows loaded", "teal"),
        kpi("🏛️", "Columns", fmt_int(df.shape[1]), "", "amber"),
        kpi("⏱️", "Load time", human_seconds(meta.get("load_seconds")), meta.get("engine", ""), "orange"),
        kpi("🟢", "Status", "READY", "data loaded", "green"),
    ])
    if meta.get("sampled"):
        st.warning(f"⚠️ The file has {fmt_int(meta['total_rows'])} records, above the in-memory limit of {fmt_int(max_rows)}. "
                   f"Analysis uses a uniform sample of {fmt_int(len(df))} rows; record counts show the exact source total.")
    if meta.get("parquet_path"):
        ratio = f" ({meta['size_bytes'] / meta['parquet_bytes']:.1f}× smaller)" if meta.get("parquet_bytes") and meta.get("size_bytes") and meta["format"] != "GENERATED" else ""
        st.markdown(badge("PARQUET", "success") + f" saved to `{meta['parquet_path']}` · {human_bytes(meta['parquet_bytes'])}{ratio}",
                    unsafe_allow_html=True)

    with st.expander("🧬 Detected data types", expanded=False):
        styled_table(helpers.memo("dtype_report", lambda: cleaning.dtype_report(df)), height=min(460, 60 + 36 * df.shape[1]))
    explorer(df, key="ingest")
