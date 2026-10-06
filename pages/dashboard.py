"""Main dashboard: KPIs, pipeline status, quality, insights and overview charts."""
from __future__ import annotations

import streamlit as st

import config
from components import charts
from components.kpi_cards import kpi, render_kpis
from components.metrics import dimension_bars, hero, insight_card, quality_ring, stage_stepper
from services import analytics, cleaning, data_quality
from utils import helpers
from utils.formatters import fmt_int, fmt_pct, human_bytes, human_number, human_seconds


def render() -> None:
    st.markdown(hero(config.APP_NAME, config.APP_TAGLINE, small=False), unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    meta, ds = helpers.get_meta(), helpers.get_ds()
    rep = helpers.memo("quality", lambda: data_quality.assess(df))
    c = rep.counts
    pipe = ds["pipeline"]
    report = pipe.get("report")
    mem = helpers.memo("memory", lambda: int(df.memory_usage(deep=False).sum()))

    sampled = meta.get("sampled")
    render_kpis([
        kpi("🧮", "Total Records", human_number(helpers.total_records()),
            f"analysing {fmt_int(len(df))} (sampled)" if sampled else "exact count", "blue"),
        kpi("💾", "Data Size", human_bytes(meta.get("size_bytes") or mem), f"{human_bytes(mem)} in memory", "violet"),
        kpi("🏛️", "Columns", fmt_int(df.shape[1]), "", "teal"),
        kpi("⏱️", "Processing Time", human_seconds(report["seconds"] if report else meta.get("load_seconds")),
            "last pipeline run" if report else f"load time · {meta.get('engine', '')}", "orange"),
        kpi("✅", "Data Quality", f"{rep.score:.1f}%", rep.label, "green"),
        kpi("🕳️", "Missing Values", fmt_pct(c["missing_pct"]), f"{fmt_int(c['missing_cells'])} cells", "amber"),
        kpi("♊", "Duplicates", fmt_pct(c["duplicate_pct"]), f"{fmt_int(c['duplicates'])} rows", "rose"),
        kpi("📌", "Outliers", fmt_int(c["outliers"]), "IQR rule, numeric columns", "slate"),
    ])

    stages = [(s, pipe["stages"][s]) for s in helpers.STAGES]
    st.markdown(f"<div class='card'><div class='card-title'>Pipeline status</div>{stage_stepper(stages)}</div>",
                unsafe_allow_html=True)
    b1, b2, b3, _ = st.columns([1, 1, 1, 3])
    b1.button("🛡️ Data quality", on_click=helpers.goto, args=("Data Quality",), use_container_width=True, key="dash_q")
    b2.button("⚙️ Run pipeline", on_click=helpers.goto, args=("Processing",), use_container_width=True, key="dash_p")
    b3.button("💡 Insights", on_click=helpers.goto, args=("Insights",), use_container_width=True, key="dash_i")

    left, right = st.columns([1, 1.5])
    with left:
        st.markdown(quality_ring(rep.score, rep.label), unsafe_allow_html=True)
        st.markdown(dimension_bars(rep.dimensions), unsafe_allow_html=True)
    with right:
        st.markdown("<div class='card-title'>💡 Top insights</div>", unsafe_allow_html=True)
        insights = helpers.memo("insights", lambda: analytics.generate_insights(df, rep, st.session_state.get("corr_threshold", 0.6)))
        for item in insights[:5]:
            st.markdown(insight_card(item), unsafe_allow_html=True)

    st.markdown("### Overview")
    g1, g2 = st.columns(2)
    dts, measure = analytics.datetime_cols(df), analytics.pick_measure(df)
    with g1:
        if dts:
            ts = helpers.memo("dash_trend", lambda: analytics.temporal_trends(df, dts[0], measure, "Sum", "Monthly"))
            charts.show(charts.trend_chart(ts, f"Monthly {measure or 'records'}"), key="dash_trend")
        else:
            st.info("No date column detected — convert one in Processing to unlock trend charts.")
    with g2:
        cats = analytics.low_cardinality_cols(df, 30)
        if cats:
            top = analytics.top_categories(df, cats[0], 10)
            charts.show(charts.bar_chart(top, cats[0], "Count", f"Top {cats[0]} values", horizontal=True), key="dash_top")
        else:
            st.info("No low-cardinality categorical column found.")
    g3, g4 = st.columns(2)
    with g3:
        types = helpers.memo("dtype_counts", lambda: cleaning.dtype_report(df)["Detected type"].value_counts())
        charts.show(charts.donut(list(types.index), [int(v) for v in types.values], "Column types"), key="dash_types")
    with g4:
        miss = (df.isna().mean() * 100).sort_values(ascending=False).head(10)
        miss = miss[miss > 0]
        if miss.empty:
            st.success("✅ No missing values in any column.")
        else:
            import pandas as pd
            charts.show(charts.bar_chart(pd.DataFrame({"Column": miss.index, "Missing %": miss.values}), "Column",
                                         "Missing %", "Missing values by column (%)", horizontal=True), key="dash_miss")
