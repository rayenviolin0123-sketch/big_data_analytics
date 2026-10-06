"""Big Data Analytics Dashboard — entry point.  Run with:  streamlit run app.py"""
import sys
from pathlib import Path

import streamlit as st

try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
except ImportError:  # very old / very new Streamlit layouts
    get_script_run_ctx = None

# `python app.py` (bare mode) cannot display a UI — explain how to start it.
if get_script_run_ctx is not None and get_script_run_ctx() is None:
    print("\nThis is a Streamlit app. Start it with:\n\n    python -m streamlit run app.py\n")
    sys.exit(0)

import config  # noqa: E402

st.set_page_config(page_title="Big Data Analytics", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

from components.navbar import render_navbar  # noqa: E402
from components.sidebar import render_sidebar  # noqa: E402
from pages import (big_data_stats, correlations, dashboard, data_ingestion, data_quality,  # noqa: E402
                   exploratory_analysis, export, insights, processing, visualization)
from utils import helpers  # noqa: E402

ROUTES = {
    "Dashboard": dashboard.render,
    "Data Ingestion": data_ingestion.render,
    "Data Quality": data_quality.render,
    "Processing": processing.render,
    "Exploratory Analysis": exploratory_analysis.render,
    "Visualization Studio": visualization.render,
    "Big Data Stats": big_data_stats.render,
    "Correlations": correlations.render,
    "Insights": insights.render,
    "Export": export.render,
}


def main() -> None:
    helpers.ensure_dirs()
    css = config.ASSETS_DIR / "style.css"
    if css.exists():
        st.markdown(f"<style>{css.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    page = render_sidebar()
    render_navbar(page)
    try:
        ROUTES[page]()
    except Exception as exc:  # noqa: BLE001 - last line of defence: friendly message, never a raw traceback
        st.error(f"⚠️ Something went wrong while rendering this page: {exc}")
        st.caption("Try 'Reset to original data' in the sidebar, or load a different dataset.")


main()
