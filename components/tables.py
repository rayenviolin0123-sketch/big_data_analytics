"""Interactive tables: styled dataframe, filter panel and a paginated data explorer."""
from __future__ import annotations

import math
from typing import List

import pandas as pd
import streamlit as st

from services import analytics
from utils import helpers
from utils.formatters import fmt_int
from utils.validators import is_datetime, is_numeric, is_text


def styled_table(df: pd.DataFrame, height: int = 380, key: str | None = None) -> None:
    st.dataframe(df, use_container_width=True, height=height, hide_index=True, key=key)


def filter_panel(df: pd.DataFrame, key: str, max_filters: int = 3) -> List[dict]:
    """Render up to ``max_filters`` column filters and return them as filter dicts for analytics.apply_filters."""
    filters: List[dict] = []
    n = st.number_input("Number of filters", 0, max_filters, 0, key=f"{key}_nf")
    for i in range(int(n)):
        c1, c2 = st.columns([1, 2])
        col = c1.selectbox("Column", list(df.columns), key=f"{key}_fc{i}")
        s = df[col]
        if is_numeric(s):
            lo, hi = helpers.memo("minmax", lambda s=s: (s.min(), s.max()), col)
            if pd.notna(lo) and pd.notna(hi) and lo < hi:
                ints = pd.api.types.is_integer_dtype(s)
                lo, hi = (int(lo), int(hi)) if ints else (float(lo), float(hi))
                v = c2.slider("Range", lo, hi, (lo, hi), key=f"{key}_r{i}_{col}")
                filters.append({"col": col, "kind": "range", "value": v})
        elif is_datetime(s):
            lo, hi = s.min(), s.max()
            if pd.notna(lo):
                v = c2.date_input("Date range", (lo.date(), hi.date()), key=f"{key}_d{i}_{col}")
                if isinstance(v, (tuple, list)) and len(v) == 2:
                    filters.append({"col": col, "kind": "date", "value": tuple(v)})
        else:
            uniq = helpers.memo("uniq", lambda s=s: s.dropna().unique().tolist()[:5001], col)
            if len(uniq) > 1000:
                c2.caption("Too many distinct values — use search instead.")
            else:
                try:
                    uniq = sorted(uniq)
                except TypeError:
                    pass
                chosen = c2.multiselect("Values", uniq, key=f"{key}_v{i}_{col}")
                if chosen:
                    filters.append({"col": col, "kind": "in", "value": chosen})
    return filters


def explorer(df: pd.DataFrame, key: str = "explorer") -> pd.DataFrame:
    """Searchable, sortable, filterable, paginated preview. Returns the filtered frame."""
    c1, c2, c3 = st.columns([2.2, 2.2, 1])
    search = c1.text_input("🔎 Search", placeholder="Search text columns…", key=f"{key}_s")
    cols = c2.multiselect("Columns", list(df.columns), default=list(df.columns), key=f"{key}_c")
    page_size = c3.selectbox("Rows per page", [25, 50, 100, 250, 500], index=2, key=f"{key}_n")

    view = df[cols] if cols else df.iloc[:, :0]
    with st.expander("🎚️ Filters & sorting"):
        filters = filter_panel(df, f"{key}_f")
        scol = st.selectbox("Sort by", ["—"] + list(view.columns), key=f"{key}_sc")
        asc = st.toggle("Ascending", True, key=f"{key}_asc")
    view = analytics.apply_filters(df, filters)[cols] if cols else view.iloc[:0]
    if scol != "—" and scol in view.columns:
        view = view.sort_values(scol, ascending=asc, na_position="last")
    if search.strip() and len(view.columns):
        text_cols = [c for c in view.columns if is_text(view[c])]
        if text_cols:
            mask = pd.Series(False, index=view.index)
            for c in text_cols:
                mask |= view[c].astype("string").str.contains(search.strip(), case=False, regex=False, na=False)
            view = view[mask]

    total = len(view)
    pages = max(1, math.ceil(total / page_size))
    p1, p2 = st.columns([4, 1])
    page = p2.number_input("Page", 1, pages, 1, key=f"{key}_p", help=f"{pages:,} page(s)")
    start = (int(page) - 1) * page_size
    chunk = view.iloc[start:start + page_size]
    filtered_note = f" (filtered from {fmt_int(len(df))})" if total != len(df) else ""
    p1.markdown(f"**Dataset Preview**  \nShowing {fmt_int(len(chunk))} of {fmt_int(total)} rows{filtered_note} · page {int(page)} of {pages:,}")
    styled_table(chunk, height=440)
    return view
