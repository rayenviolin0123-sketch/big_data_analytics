"""Data quality page: dimensions, global score, issues, per-column table, outliers."""
from __future__ import annotations

import streamlit as st

import config
from components import charts
from components.metrics import dimension_bars, hero, quality_ring, status_badge
from components.tables import styled_table
from services import analytics, cleaning, data_quality
from utils import helpers
from utils.formatters import fmt_int


def render() -> None:
    st.markdown(hero("🛡️ Data Quality", "Completeness · Accuracy · Consistency · Uniqueness · Validity"), unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    with st.spinner("Assessing data quality …"):
        rep = helpers.memo("quality", lambda: data_quality.assess(df))

    left, right = st.columns([1, 1.3])
    with left:
        st.markdown(quality_ring(rep.score, rep.label, "DATA QUALITY SCORE"), unsafe_allow_html=True)
    with right:
        st.markdown(dimension_bars(rep.dimensions), unsafe_allow_html=True)
    if rep.sampled:
        st.caption("ℹ️ Validity and consistency are estimated on a random sample of "
                   f"{fmt_int(config.ANALYSIS_SAMPLE)} rows; missing, duplicate and outlier checks use all analysed rows.")
    with st.expander("How is the score calculated?"):
        st.markdown(
            "- **Completeness** – share of non-missing cells.\n"
            "- **Uniqueness** – share of rows that are not exact duplicates.\n"
            "- **Validity** – values that match the column's evident type (e.g. `N/A` in a numeric column, infinities).\n"
            "- **Consistency** – text free of case/whitespace variants (`France`, `france `) and mixed types.\n"
            "- **Accuracy** – numeric values not beyond 3×IQR fences (a proxy: extreme values are *potentially* wrong).\n\n"
            "Global score = 25% Completeness + 20% Accuracy + 15% Consistency + 20% Uniqueness + 20% Validity.")

    st.markdown("### Issues detected")
    issues = rep.issues.copy()
    rows = "".join(
        f"<tr><td>{r['Check']}</td><td style='text-align:right'>{fmt_int(r['Count'])}</td>"
        f"<td style='text-align:right'>{r['Percent']:.2f}%</td><td>{status_badge(r['Status'])}</td></tr>"
        for _, r in issues.iterrows())
    st.markdown(
        "<div class='card'><table style='width:100%;border-collapse:collapse'><thead><tr style='text-align:left;color:#64748b;font-size:.8rem'>"
        "<th>Check</th><th style='text-align:right'>Count</th><th style='text-align:right'>Share</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>", unsafe_allow_html=True)

    c = rep.counts
    if c["incorrect_types"]:
        st.warning(f"⚠️ {c['incorrect_types']} text column(s) look numeric, boolean or date-like.")
        if st.button("🔧 Convert suggested types automatically", key="dq_fix_types"):
            new_df, done = cleaning.auto_convert_suggested(df)
            helpers.update_df(new_df, "Converted types: " + ", ".join(done))
            st.rerun()

    st.markdown("### Column-level report")
    styled_table(rep.columns.round(2), height=min(480, 60 + 36 * len(rep.columns)))

    st.markdown("### Outlier inspection")
    nums = analytics.numeric_cols(df)
    if not nums:
        st.info("No numeric columns to inspect.")
        return
    col = st.selectbox("Column", nums, key="dq_out_col")
    res = cleaning.outlier_bounds(df[col], "IQR")
    if res is None:
        st.warning("⚠️ This column has no finite numeric values.")
        return
    n_out = int(cleaning.outlier_mask(df[col], "IQR").sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("Lower bound", f"{res[0]:,.2f}")
    m2.metric("Upper bound", f"{res[1]:,.2f}")
    m3.metric("Outliers", fmt_int(n_out))
    charts.show(charts.box_plot(df[col], col), key="dq_box")
