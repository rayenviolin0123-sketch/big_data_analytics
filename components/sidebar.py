"""Sidebar: branding, navigation, dataset summary and global settings."""
from __future__ import annotations

import streamlit as st

import config
from utils import helpers
from utils.formatters import fmt_int, human_bytes
from utils.helpers import esc

LABELS = {f"{icon}  {name}": name for name, icon in config.NAV_ITEMS}
_ICON = dict(config.NAV_ITEMS)


def _fmt(name: str) -> str:
    return f"{_ICON[name]}  {name}"


def render_sidebar() -> str:
    """Draw the sidebar and return the selected page name."""
    with st.sidebar:
        st.markdown(
            "<div class='brand'><div class='brand-logo'>◢</div><div><div class='brand-name'>BIG DATA</div>"
            "<div class='brand-sub'>ANALYTICS PLATFORM</div></div></div>", unsafe_allow_html=True)
        st.divider()
        if "nav" not in st.session_state:
            st.session_state["nav"] = config.NAV_ITEMS[0][0]
        page = st.radio("Navigation", [n for n, _ in config.NAV_ITEMS], format_func=_fmt,
                        label_visibility="collapsed", key="nav")
        st.divider()

        if helpers.has_data():
            meta, df = helpers.get_meta(), helpers.get_df()
            sample_note = " · sampled" if meta.get("sampled") else ""
            st.markdown(
                f"<div class='side-card'><div class='side-label'>ACTIVE DATASET</div>"
                f"<div class='side-title'>{esc(meta.get('name', 'dataset'))}</div>"
                f"<div class='side-meta'>{fmt_int(helpers.total_records())} records · {df.shape[1]} cols</div>"
                f"<div class='side-meta'>{human_bytes(meta.get('size_bytes', 0))} · {esc(meta.get('format', ''))}{sample_note}</div></div>",
                unsafe_allow_html=True)
            if st.button("↩ Reset to original data", use_container_width=True, key="sb_reset"):
                helpers.reset_to_original()
                st.rerun()
        else:
            st.markdown("<div class='side-card'><div class='side-label'>ACTIVE DATASET</div>"
                        "<div class='side-meta'>None loaded</div></div>", unsafe_allow_html=True)

        with st.expander("⚙ Settings"):
            st.selectbox("Chart theme", ["plotly_white", "plotly", "plotly_dark", "ggplot2", "seaborn", "simple_white"],
                         key="plotly_theme")
            st.slider("Strong-correlation threshold", 0.3, 0.95, 0.6, 0.05, key="corr_threshold")
            st.number_input("Max rows kept in memory", 10_000, 50_000_000, config.MAX_ROWS_IN_MEMORY, 100_000,
                            key="max_rows", help="Larger files are streamed and sampled uniformly.")
        st.caption("v1.0 · Python · Streamlit")
    return page
