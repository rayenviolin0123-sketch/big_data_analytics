"""Top navigation bar: breadcrumb, engine badges, dataset chip."""
from __future__ import annotations

import streamlit as st

from components.metrics import badge
from utils import helpers
from utils.formatters import human_number
from utils.helpers import esc


def render_navbar(page: str) -> None:
    engines = "".join(badge(e["name"], "success") if e["installed"] else badge(e["name"], "neutral")
                      for e in helpers.engine_status() if not e["optional"])
    meta = helpers.get_meta()
    if helpers.has_data():
        chip = (f"<span class='chip'>📄 {esc(meta.get('name', 'dataset'))} · "
                f"{human_number(helpers.total_records())} records</span>" + badge("● LIVE", "success"))
    else:
        chip = badge("● NO DATA", "neutral")
    st.markdown(
        f"<div class='navbar'><div class='crumbs'><span class='crumb-root'>Platform</span>"
        f"<span class='crumb-sep'>/</span><span class='crumb-page'>{esc(page)}</span></div>"
        f"<div class='nav-right'><span class='engines'>{engines}</span>{chip}</div></div>",
        unsafe_allow_html=True)
