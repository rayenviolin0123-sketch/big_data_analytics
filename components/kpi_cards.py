"""KPI card grid (single responsive CSS grid instead of fixed Streamlit columns)."""
from __future__ import annotations

from typing import List, Optional, TypedDict

import streamlit as st

from utils.helpers import esc


class Card(TypedDict, total=False):
    icon: str
    label: str
    value: str
    sub: str
    tone: str


def kpi(icon: str, label: str, value: str, sub: str = "", tone: str = "blue") -> Card:
    return {"icon": icon, "label": label, "value": value, "sub": sub, "tone": tone}


def render_kpis(cards: List[Card], min_width: int = 210) -> None:
    html_cards = []
    for c in cards:
        sub = f"<div class='kpi-sub'>{esc(c['sub'])}</div>" if c.get("sub") else ""
        html_cards.append(
            f"<div class='kpi kpi-{esc(c.get('tone', 'blue'))}'><div class='kpi-icon'>{esc(c['icon'])}</div>"
            f"<div class='kpi-body'><div class='kpi-label'>{esc(c['label'])}</div>"
            f"<div class='kpi-value'>{esc(c['value'])}</div>{sub}</div></div>")
    st.markdown(f"<div class='kpi-grid' style='--min:{min_width}px'>{''.join(html_cards)}</div>", unsafe_allow_html=True)
