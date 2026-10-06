"""Big Data stats: engines, data footprint, distribution diagnostics, SQL console, Spark & Kafka adapters."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

import config
from components import charts
from components.metrics import badge, hero
from components.tables import styled_table
from services import analytics, processing
from utils import helpers
from utils.formatters import fmt_int, human_bytes, human_seconds

EXAMPLES = {
    "Top 10 by sum": "SELECT {cat}, COUNT(*) AS records, ROUND(SUM({num}), 2) AS total\nFROM dataset\nGROUP BY {cat}\nORDER BY total DESC\nLIMIT 10",
    "Summary of all columns": "SUMMARIZE dataset",
    "Monthly totals": "SELECT date_trunc('month', {dt}) AS month, ROUND(SUM({num}), 2) AS total\nFROM dataset\nGROUP BY 1\nORDER BY 1",
    "Preview": "SELECT * FROM dataset LIMIT 100",
}


def _engines_section() -> None:
    st.markdown("### Processing engines")
    rows = "".join(
        f"<tr><td><b>{e['name']}</b></td><td>{e['role']}</td><td>"
        f"{badge('INSTALLED', 'success') if e['installed'] else badge('NOT INSTALLED', 'neutral')}"
        f"{' ' + badge('optional', 'info') if e['optional'] else ''}</td></tr>" for e in helpers.engine_status())
    st.markdown(f"<div class='card'><table style='width:100%'><thead><tr style='text-align:left;color:#64748b;font-size:.8rem'>"
                f"<th>Engine</th><th>Role</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>", unsafe_allow_html=True)
    st.markdown("<div class='arch'>Raw Data\n   ↓  streaming read (Polars lazy scan / DuckDB / pandas chunks)\nIngestion  →  exact record count + uniform sample\n"
                "   ↓\nParquet  (columnar, Snappy-compressed)\n   ↓\nPolars / DuckDB  (SQL + vectorised analytics)\n   ↓\nCleaning → Analytics → Visualization → Export\n\n"
                "Optional:  Kafka ─▶ micro-batches ─▶ pipeline      PySpark ─▶ distributed group-by on Parquet</div>", unsafe_allow_html=True)


def render() -> None:
    st.markdown(hero("🧮 Big Data Stats", "Engines · footprint · diagnostics · SQL · Spark & Kafka adapters"), unsafe_allow_html=True)
    _engines_section()
    df = helpers.get_df()
    if df is None:
        st.info("Load a dataset to see footprint statistics and use the SQL console.")
        return
    meta = helpers.get_meta()

    t_fp, t_diag, t_sql, t_adapt = st.tabs(["💾 Footprint", "📐 Distribution diagnostics", "🗄️ SQL console", "🔌 Spark & Kafka"])

    with t_fp:
        mem = helpers.memo("mem_breakdown", lambda: analytics.memory_breakdown(df))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Source records", fmt_int(helpers.total_records()))
        c2.metric("Rows in memory", fmt_int(len(df)))
        c3.metric("Est. memory", human_bytes(mem["Memory (MB)"].sum() * 1024 ** 2))
        c4.metric("Bytes / row", fmt_int(mem["Memory (MB)"].sum() * 1024 ** 2 / max(len(df), 1)))
        if meta.get("parquet_bytes"):
            raw = meta.get("size_bytes") or 0
            st.success(f"Parquet copy: {human_bytes(meta['parquet_bytes'])}"
                       + (f" vs source file {human_bytes(raw)} → {raw / meta['parquet_bytes']:.1f}× smaller" if raw and meta.get("format") not in ("GENERATED", "PARQUET") else ""))
        charts.show(charts.memory_bar(mem), key="bd_mem")
        card = helpers.memo("cardinality", lambda: pd.DataFrame({
            "Column": df.columns, "Distinct (est.)": [int((df[c] if len(df) <= 100_000 else df[c].sample(100_000, random_state=1)).nunique()) for c in df.columns],
            "Missing %": [df[c].isna().mean() * 100 for c in df.columns]}))
        styled_table(card.round(2), height=min(420, 60 + 36 * len(card)))

    with t_diag:
        st.caption("D'Agostino–Pearson normality test on up to 5,000 sampled values. With very large samples almost any "
                   "real data 'fails' — judge by skew/kurtosis and plots as well as by p.")
        tests = helpers.memo("normality", lambda: analytics.normality_tests(df))
        if tests.empty:
            st.info("No suitable numeric columns.")
        else:
            styled_table(tests.round(4), height=min(420, 60 + 36 * len(tests)))
            col = st.selectbox("Plot", tests["Column"], key="bd_norm_col")
            charts.show(charts.histogram(df[col], col), key="bd_norm_hist")

    with t_sql:
        engine = "DuckDB" if helpers.HAS_DUCKDB else "SQLite (fallback — install DuckDB for speed)"
        st.caption(f"Engine: **{engine}** · the working data is exposed as the table `dataset` · read-only queries only. "
                   "Intended for local use.")
        cat = (analytics.low_cardinality_cols(df) or [df.columns[0]])[0]
        num = analytics.pick_measure(df) or df.columns[0]
        dt = (analytics.datetime_cols(df) or [df.columns[0]])[0]
        ex = st.selectbox("Example queries", list(EXAMPLES), key="sql_ex")
        if st.session_state.get("_sql_ex_prev") != ex:
            st.session_state["sql_text"] = EXAMPLES[ex].format(cat=f'"{cat}"', num=f'"{num}"', dt=f'"{dt}"')
            st.session_state["_sql_ex_prev"] = ex
        q = st.text_area("SQL", key="sql_text", height=140)
        if st.button("▶ Run query", type="primary", key="sql_run"):
            try:
                t0 = time.perf_counter()
                res = analytics.run_sql(df, q)
                st.success(f"{fmt_int(len(res))} row(s) in {human_seconds(time.perf_counter() - t0)}")
                styled_table(res, height=360)
                st.session_state["sql_result"] = res
            except ValueError as exc:
                st.warning(f"⚠️ {exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"⚠️ Query failed: {exc}")

    with t_adapt:
        st.markdown("#### PySpark (optional)")
        st.markdown(badge("INSTALLED", "success") if helpers.HAS_PYSPARK else badge("NOT INSTALLED — pip install pyspark (Java 11+)", "neutral"),
                    unsafe_allow_html=True)
        st.code(processing.SPARK_SNIPPET, language="python")
        pq = meta.get("parquet_path")
        if helpers.HAS_PYSPARK and pq:
            c1, c2, c3 = st.columns(3)
            g = c1.selectbox("Group by", analytics.low_cardinality_cols(df) or list(df.columns), key="sp_g")
            v = c2.selectbox("Value", analytics.measure_columns(df) or [None], key="sp_v")
            a = c3.selectbox("Aggregation", ["sum", "mean", "min", "max", "count"], key="sp_a")
            if st.button("Run Spark job", key="sp_run"):
                try:
                    with st.spinner("Starting local Spark session …"):
                        res = processing.spark_aggregate(pq, g, v, a)
                    styled_table(res, height=320)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"⚠️ Spark job failed: {exc}")
        elif helpers.HAS_PYSPARK:
            st.info("Enable 'Convert to Parquet on ingestion' (or run the pipeline) to give Spark a Parquet file to read.")

        st.markdown("#### Apache Kafka (optional)")
        st.markdown(badge("INSTALLED", "success") if helpers.HAS_KAFKA else badge("NOT INSTALLED — pip install kafka-python", "neutral"),
                    unsafe_allow_html=True)
        st.code(processing.KAFKA_SNIPPET, language="python")
        if helpers.HAS_KAFKA:
            c1, c2, c3 = st.columns(3)
            topic = c1.text_input("Topic", key="kf_topic")
            server = c2.text_input("Bootstrap server", "localhost:9092", key="kf_srv")
            n = c3.number_input("Max messages", 10, 100_000, 1000, key="kf_n")
            if st.button("Consume batch", disabled=not topic, key="kf_run"):
                try:
                    with st.spinner("Consuming …"):
                        batch = processing.kafka_consume_batch(topic, server, int(n))
                    if batch.empty:
                        st.info("No messages received before the timeout.")
                    else:
                        st.success(f"Received {len(batch):,} messages")
                        styled_table(batch.head(500), height=320)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"⚠️ Kafka consumer failed: {exc}")
