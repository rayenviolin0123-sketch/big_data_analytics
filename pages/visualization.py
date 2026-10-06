"""Visualization Studio: interactive chart builder with filters and aggregation."""
from __future__ import annotations

import streamlit as st

import config
from components import charts
from components.metrics import hero
from components.tables import filter_panel
from services import analytics
from utils import helpers
from utils.formatters import fmt_int

NONE = "— none —"


def render() -> None:
    st.markdown(hero("📈 Visualization Studio", "Interactive charts — aggregated before plotting, so any data size stays fast"),
                unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    cols = list(df.columns)
    opt = [None] + cols
    fmt = lambda v: NONE if v is None else v  # noqa: E731

    with st.container():
        c1, c2, c3 = st.columns(3)
        kind = c1.selectbox("Chart type", config.CHART_TYPES, key="viz_kind")
        x = c2.selectbox("X axis", opt, format_func=fmt, index=1 if cols else 0, key="viz_x")
        measures = analytics.measure_columns(df)
        y_default = (cols.index(measures[0]) + 1) if measures else 0
        y = c3.selectbox("Y axis", opt, format_func=fmt, index=y_default, key="viz_y")
        c4, c5, c6, c7 = st.columns(4)
        group = c4.selectbox("Group by", opt, format_func=fmt, key="viz_group")
        color = c5.selectbox("Color", opt, format_func=fmt, key="viz_color")
        agg = c6.selectbox("Aggregation", list(config.AGGREGATIONS), key="viz_agg")
        top_n = c7.slider("Top N categories", 5, 100, 30, key="viz_topn")
        if kind == "Time Series":
            freq = st.radio("Time bucket", ["Auto", "Daily", "Weekly", "Monthly", "Yearly"], horizontal=True, key="viz_freq")
        else:
            freq = "Auto"
    with st.expander("🎚️ Filters"):
        filters = filter_panel(df, "viz_f")

    try:
        data = analytics.apply_filters(df, filters)
        if len(data) != len(df):
            st.caption(f"Filtered: {fmt_int(len(data))} of {fmt_int(len(df))} rows")
        fig, note = charts.build_chart(data, kind, x, y, group, color, agg, top_n, freq)
        charts.show(fig, key="viz_main")
        st.session_state["last_fig"] = fig
        st.caption(f"ℹ️ {note}  ·  Tip: drag to zoom, scroll to pan, click the legend to toggle series, camera icon = PNG.")
    except ValueError as exc:
        st.warning(f"⚠️ {exc}")
    except Exception as exc:  # noqa: BLE001 - keep the app alive on any odd dataset
        st.error(f"⚠️ This chart could not be created with the selected columns. ({exc})")
