"""Processing page: live pipeline monitor and interactive cleaning tools."""
from __future__ import annotations

import streamlit as st

import config
from components.metrics import badge, hero, processing_monitor
from components.tables import styled_table
from services import analytics, cleaning, processing
from utils import helpers
from utils.formatters import fmt_int, human_bytes, human_seconds
from utils.validators import is_numeric

STAGE_MAP = {0: "DATA LOADED", 1: "DATA CLEANED", 2: "DATA PROCESSED", 3: "ANALYSIS READY"}


def _stage_list(states: dict) -> list[tuple[str, str]]:
    return [(s, states.get(s, "pending")) for s in helpers.STAGES]


def _monitor_tab(df) -> None:
    ds = helpers.get_ds()
    pipe = ds["pipeline"]
    meta = helpers.get_meta()
    st.markdown("<div class='arch'>Raw Data → Ingestion → Parquet → Polars / DuckDB → Cleaning → Analytics → Visualization</div>",
                unsafe_allow_html=True)
    with st.expander("⚙️ Pipeline options", expanded=True):
        c1, c2, c3 = st.columns(3)
        o_text = c1.checkbox("Standardize text (trim, collapse spaces, blank → missing)", True, key="po_text")
        o_dup = c1.checkbox("Remove duplicate records", True, key="po_dup")
        o_fill = c2.checkbox("Fill missing (numeric→median, text→mode, dates→ffill)", True, key="po_fill")
        o_cap = c2.checkbox("Cap outliers (winsorize)", False, key="po_cap")
        o_method = c3.selectbox("Outlier method", cleaning.OUTLIER_METHODS, key="po_method", disabled=not o_cap)
        o_pq = c3.checkbox("Write cleaned Parquet", helpers.HAS_PYARROW, key="po_pq", disabled=not helpers.HAS_PYARROW)

    placeholder = st.empty()
    report = pipe.get("report")
    if report:
        placeholder.markdown(processing_monitor(100, report["rows_in"], report["rows_in"], report["rows_per_sec"],
                                                report["seconds"], _stage_list(pipe["stages"])), unsafe_allow_html=True)
    else:
        placeholder.markdown(processing_monitor(0, 0, len(df), float("nan"), 0, _stage_list(pipe["stages"])),
                             unsafe_allow_html=True)

    if st.button("▶ Run pipeline", type="primary", key="run_pipeline"):
        opts = processing.PipelineOptions(o_text, o_dup, o_fill, o_cap, o_method, o_pq)
        states = {s: "pending" for s in helpers.STAGES}
        states[helpers.STAGES[0]] = "done"
        bar = st.progress(0)

        def on_progress(pct, done, total, elapsed, stage_idx):
            for i, s in enumerate(helpers.STAGES):
                states[s] = "done" if i < stage_idx or (pct >= 100) else "running" if i == stage_idx else "pending"
            speed = done / elapsed if elapsed > 0 else float("nan")
            placeholder.markdown(processing_monitor(pct, done, total, speed, elapsed, _stage_list(states)),
                                 unsafe_allow_html=True)
            bar.progress(min(int(pct), 100))

        try:
            new_df, rep = processing.run_pipeline(df, opts, meta.get("name", "dataset"), on_progress)
        except Exception as exc:  # noqa: BLE001 - never crash the app on a bad dataset
            st.error(f"⚠️ The pipeline failed: {exc}")
            return
        helpers.update_df(new_df, f"Pipeline: -{rep['duplicates_removed']:,} duplicates, {rep['missing_filled']:,} filled, "
                                  f"{rep['outliers_capped']:,} capped")
        ds = helpers.get_ds()
        ds["pipeline"] = {"stages": {s: "done" for s in helpers.STAGES}, "report": {k: v for k, v in rep.items() if k != "quality"}}
        helpers.memo_set("quality", rep["quality"])
        if rep.get("parquet_path"):
            ds["meta"]["parquet_path"] = rep["parquet_path"]
            ds["meta"]["parquet_bytes"] = rep["parquet_bytes"]
        st.success(f"✅ Pipeline finished in {human_seconds(rep['seconds'])} · "
                   f"{fmt_int(rep['rows_in'])} → {fmt_int(rep['rows_out'])} records · quality now {rep['quality'].score:.1f}/100")
        st.rerun()

    if report:
        st.markdown("#### Last run summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Duplicates removed", fmt_int(report["duplicates_removed"]))
        c2.metric("Missing values filled", fmt_int(report["missing_filled"]))
        c3.metric("Text cells standardized", fmt_int(report["text_cells_standardized"]))
        c4.metric("Outliers capped", fmt_int(report["outliers_capped"]))
        if report.get("parquet_path"):
            st.markdown(badge("PARQUET", "success") + f" `{report['parquet_path']}` · {human_bytes(report['parquet_bytes'])}",
                        unsafe_allow_html=True)


def _apply(new_df, msg: str) -> None:
    if new_df is not None:
        helpers.update_df(new_df, msg)
        st.session_state["flash"] = msg
        st.rerun()


def _cleaning_tab(df) -> None:
    if "flash" in st.session_state:
        msg = st.session_state.pop("flash")
        (st.warning if "⚠️" in msg else st.success)(msg)
    t_miss, t_dup, t_type, t_out, t_log = st.tabs(["Missing values", "Duplicates", "Data types", "Outliers", "Change log"])

    with t_miss:
        table = cleaning.missing_summary(df)
        if table.empty:
            st.success("✅ No missing values.")
        else:
            styled_table(table.assign(**{"Missing %": table["Missing %"].map("{:.2f}%".format)}), height=min(300, 60 + 36 * len(table)))
            c1, c2, c3 = st.columns([2, 2, 2])
            col = c1.selectbox("Column", table["Column"].tolist(), key="cl_mcol")
            strat = c2.selectbox("Strategy", cleaning.MISSING_STRATEGIES, key="cl_mstrat")
            custom = c3.text_input("Custom value", key="cl_mcustom", disabled=strat != "Custom Value")
            if st.button("Apply", type="primary", key="cl_mapply"):
                new_df, msg = cleaning.apply_missing(df, col, strat, custom)
                if new_df is df:
                    st.warning(msg)
                else:
                    _apply(new_df, msg)
            if st.button("✨ Auto-fill all columns", key="cl_mauto", help="Median for numbers, mode for text, ffill for dates"):
                new_df, n = cleaning.fill_missing_auto(df)
                _apply(new_df, f"Auto-filled {n:,} missing value(s) across all columns.")

    with t_dup:
        subset = st.multiselect("Consider only these columns (empty = all)", list(df.columns), key="cl_dsub")
        dups = cleaning.duplicate_count(df, subset)
        st.markdown(f"### Duplicate records found: **{fmt_int(dups)}** ({dups / max(len(df), 1) * 100:.2f}%)")
        if dups:
            with st.expander("Preview duplicates"):
                styled_table(df[df.duplicated(subset=subset or None, keep=False)].head(200), height=300)
            if st.button("🗑️ Remove duplicates", type="primary", key="cl_dremove"):
                new_df, n = cleaning.drop_duplicates(df, subset)
                _apply(new_df, f"Removed {n:,} duplicate record(s).")
        else:
            st.success("✅ No duplicates.")

    with t_type:
        report = helpers.memo("dtype_report", lambda: cleaning.dtype_report(df))
        styled_table(report, height=min(420, 60 + 36 * len(report)))
        c1, c2 = st.columns(2)
        col = c1.selectbox("Column", list(df.columns), key="cl_tcol")
        target = c2.selectbox("Convert to", cleaning.DTYPE_LABELS, key="cl_ttarget")
        st.caption(f"Before: `{df[col].dtype}` · detected **{cleaning.detect_dtype(df[col])}**")
        b1, b2 = st.columns(2)
        if b1.button("Convert", type="primary", key="cl_tapply"):
            new_df, msg = cleaning.convert_dtype(df, col, target)
            if new_df is df:
                st.warning(msg)
            else:
                _apply(new_df, msg)
        if b2.button("🔧 Convert all suggested", key="cl_tauto"):
            new_df, done = cleaning.auto_convert_suggested(df)
            _apply(new_df, "Converted: " + (", ".join(done) if done else "nothing to convert"))

    with t_out:
        nums = analytics.numeric_cols(df)
        if not nums:
            st.info("No numeric columns.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            col = c1.selectbox("Column", nums, key="cl_ocol")
            method = c2.selectbox("Method", cleaning.OUTLIER_METHODS, key="cl_omethod")
            action = c3.selectbox("Action", cleaning.OUTLIER_ACTIONS, key="cl_oaction")
            z = c4.number_input("Z threshold", 1.5, 6.0, 3.0, 0.5, key="cl_oz", disabled=method == "IQR")
            b = cleaning.outlier_bounds(df[col], method, z)
            if b is None:
                st.warning("⚠️ This column has no finite numeric values.")
            else:
                n = int(cleaning.outlier_mask(df[col], method, z).sum())
                m1, m2, m3 = st.columns(3)
                m1.metric("Lower bound", f"{b[0]:,.2f}")
                m2.metric("Upper bound", f"{b[1]:,.2f}")
                m3.metric("Outliers", fmt_int(n))
                if st.button("Apply", type="primary", key="cl_oapply", disabled=n == 0):
                    new_df, msg = cleaning.handle_outliers(df, col, method, action, z)
                    if new_df is df:
                        st.warning(msg)
                    else:
                        _apply(new_df, msg)

    with t_log:
        log = helpers.get_log()
        for i, line in enumerate(log, 1):
            st.markdown(f"`{i:02d}` {line}")


def render() -> None:
    st.markdown(hero("⚙️ Processing & Cleaning", "Chunked pipeline · cleaning tools · live monitor"), unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    tab_a, tab_b = st.tabs(["📊 Pipeline monitor", "🧹 Cleaning tools"])
    with tab_a:
        _monitor_tab(df)
    with tab_b:
        _cleaning_tab(df)
