"""Automated insights with severity, category filter and plain-language executive summary."""
from __future__ import annotations

import streamlit as st

from components.metrics import hero, insight_card
from services import analytics, data_quality
from utils import helpers
from utils.formatters import fmt_int, human_number

CATEGORIES = ["Data health", "Distribution", "Relationships", "Trends", "Segments"]


def render() -> None:
    st.markdown(hero("💡 Insights", "Rule-based findings — 'significant' is only used when a statistical test was actually run"),
                unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    rep = helpers.memo("quality", lambda: data_quality.assess(df))
    thr = st.session_state.get("corr_threshold", 0.6)
    with st.spinner("Analysing …"):
        items = helpers.memo("insights", lambda: analytics.generate_insights(df, rep, thr))

    n_warn = sum(i["severity"] in ("warning", "critical") for i in items)
    st.markdown(
        f"<div class='card'><div class='card-title'>Executive summary</div>"
        f"Analysed <b>{human_number(helpers.total_records())}</b> records across <b>{fmt_int(df.shape[1])}</b> columns. "
        f"Data quality is <b>{rep.score:.1f}/100 ({rep.label})</b>. "
        f"<b>{len(items)}</b> findings, of which <b>{n_warn}</b> need attention.</div>", unsafe_allow_html=True)

    c1, c2 = st.columns([3, 1])
    cats = c1.multiselect("Categories", CATEGORIES, default=CATEGORIES, key="ins_cats")
    only_attention = c2.toggle("Needs attention only", False, key="ins_attn")
    shown = [i for i in items if i["category"] in cats and (not only_attention or i["severity"] in ("warning", "critical"))]
    if not shown:
        st.info("No insights match the current filters.")
    for cat in CATEGORIES:
        group = [i for i in shown if i["category"] == cat]
        if group:
            st.markdown(f"#### {cat}")
            for item in group:
                st.markdown(insight_card(item), unsafe_allow_html=True)
    st.caption("Insights are descriptive. Correlation does not imply causation; outliers are unusual, not necessarily errors.")
