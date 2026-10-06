"""Correlation analysis: matrix, heatmap, strongest pairs and a tested pair explorer."""
from __future__ import annotations

import numpy as np
import streamlit as st

import config
from components import charts
from components.metrics import hero
from components.tables import styled_table
from services import analytics
from utils import helpers
from utils.formatters import fmt_int


def render() -> None:
    st.markdown(hero("🔗 Correlations", "Pearson · Spearman · Kendall — strongest relationships first"), unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    method = st.radio("Method", ["Pearson", "Spearman", "Kendall"], horizontal=True, key="corr_method")
    threshold = st.session_state.get("corr_threshold", 0.6)
    with st.spinner("Computing correlations …"):
        corr, n_used = helpers.memo("corr", lambda: analytics.correlation_matrix(df, method), method)
    if corr.empty:
        st.warning("⚠️ Correlation analysis needs at least two numeric columns with varying values.")
        return
    note = f"Computed on {fmt_int(n_used)} rows" + (" (random sample)" if n_used < len(df) else "")
    st.caption(f"{note} · {len(corr)} numeric columns · threshold |r| ≥ {threshold:.2f} (change in sidebar settings)")
    charts.show(charts.correlation_heatmap(corr, f"{method} correlation matrix"), key="corr_heat")

    tops = analytics.top_pairs(corr, threshold)
    c1, c2 = st.columns(2)
    for slot, key, title in ((c1, "positive", "🟢 Strong positive"), (c2, "negative", "🔴 Strong negative")):
        with slot:
            st.markdown(f"**{title}**")
            t = tops[key]
            if t.empty:
                st.caption("None at this threshold.")
            else:
                styled_table(t.assign(Correlation=t["Correlation"].round(3),
                                      Strength=t["Correlation"].map(analytics.describe_strength)), height=min(320, 60 + 36 * len(t)))

    st.markdown("### Pair explorer")
    cols = list(corr.columns)
    p1, p2 = st.columns(2)
    a = p1.selectbox("Variable 1", cols, key="pair_a")
    b = p2.selectbox("Variable 2", [c for c in cols if c != a], key="pair_b")
    res = analytics.pair_test(df, a, b, method)
    if res is None:
        st.warning("⚠️ Not enough varying paired values to test this pair.")
    else:
        sig = "statistically significant" if res["p"] < 0.05 else "not statistically significant"
        st.markdown(f"**{method}** r = **{res['r']:.3f}** ({analytics.describe_strength(res['r'])}), "
                    f"p = {res['p']:.3g}, n = {fmt_int(res['n'])} → {sig} at the 5% level. "
                    "With very large n even tiny correlations are 'significant' — look at the size of r.")
    d = df[[a, b]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(d) > config.MAX_CHART_POINTS:
        d = d.sample(config.MAX_CHART_POINTS, random_state=1)
        st.caption(f"Scatter shows a random sample of {config.MAX_CHART_POINTS:,} points.")
    import plotly.express as px
    charts.show(charts.style(px.scatter(d, x=a, y=b, opacity=.45, trendline=None), f"{b} vs {a}", 420), key="pair_scatter")
    st.session_state["corr_table"] = corr
