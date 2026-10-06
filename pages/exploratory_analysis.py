"""Exploratory analysis: numerical, categorical and temporal reports."""
from __future__ import annotations

import streamlit as st

import config
from components import charts
from components.metrics import hero
from components.tables import styled_table
from services import analytics
from utils import helpers
from utils.formatters import fmt_int


def render() -> None:
    st.markdown(hero("🔍 Exploratory Analysis", "Automatic profiling of numerical, categorical and temporal data"),
                unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    t_num, t_cat, t_time = st.tabs(["🔢 Numerical", "🔤 Categorical", "📅 Temporal"])

    with t_num:
        summary = helpers.memo("num_summary", lambda: analytics.numeric_summary(df))
        if summary.empty:
            st.warning("⚠️ This dataset has no numeric columns.")
        else:
            styled_table(summary.round(3), height=min(520, 70 + 36 * len(summary)))
            col = st.selectbox("Inspect distribution of", summary["Column"], key="eda_num")
            c1, c2 = st.columns(2)
            with c1:
                charts.show(charts.histogram(df[col], col), key="eda_hist")
            with c2:
                charts.show(charts.box_plot(df[col], col), key="eda_box")

    with t_cat:
        cat = helpers.memo("cat_summary", lambda: analytics.categorical_summary(df))
        if cat.empty:
            st.warning("⚠️ This dataset has no categorical columns.")
        else:
            styled_table(cat.round(2), height=min(480, 70 + 36 * len(cat)))
            col = st.selectbox("Inspect categories of", cat["Column"], key="eda_cat")
            n = st.slider("Top N", 5, 40, 15, key="eda_cat_n")
            top = analytics.top_categories(df, col, n)
            c1, c2 = st.columns([1.4, 1])
            with c1:
                charts.show(charts.bar_chart(top, col, "Count", f"Top {n} — {col}", horizontal=True, height=420), key="eda_cat_bar")
            with c2:
                styled_table(top.round(2), height=420)

    with t_time:
        dts = analytics.datetime_cols(df)
        if not dts:
            st.info("No date/time column detected. Convert a text column to Date/Datetime in Processing → Cleaning tools.")
        else:
            c1, c2, c3 = st.columns(3)
            dcol = c1.selectbox("Date column", dts, key="eda_dcol")
            measures = ["(count records)"] + analytics.measure_columns(df)
            vcol = c2.selectbox("Measure", measures, key="eda_vcol")
            agg = c3.selectbox("Aggregation", list(config.AGGREGATIONS), key="eda_agg", disabled=vcol == "(count records)")
            mv = None if vcol == "(count records)" else vcol
            s = df[dcol].dropna()
            if s.empty:
                st.warning("⚠️ This date column has no valid values.")
            else:
                m1, m2, m3 = st.columns(3)
                m1.metric("First date", f"{s.min():%Y-%m-%d}")
                m2.metric("Last date", f"{s.max():%Y-%m-%d}")
                m3.metric("Days covered", fmt_int((s.max() - s.min()).days))
                g1, g2 = st.columns(2)
                for slot, freq in ((g1, "Daily"), (g2, "Weekly")):
                    with slot:
                        ts = analytics.temporal_trends(df, dcol, mv, agg, freq)
                        charts.show(charts.trend_chart(ts, f"{freq} trend"), key=f"eda_{freq}")
                g3, g4 = st.columns(2)
                for slot, freq in ((g3, "Monthly"), (g4, "Yearly")):
                    with slot:
                        ts = analytics.temporal_trends(df, dcol, mv, agg, freq)
                        if freq == "Yearly":
                            ts = ts.assign(**{dcol: ts[dcol].dt.year.astype(str)})
                            charts.show(charts.bar_chart(ts, dcol, ts.columns[1], "Yearly trend"), key="eda_Yearly")
                        else:
                            charts.show(charts.trend_chart(ts, f"{freq} trend"), key=f"eda_{freq}")
