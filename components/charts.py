"""Plotly chart builders. Heavy work (binning, aggregation, sampling) happens in pandas/NumPy first so the
browser only ever receives a bounded number of points, however large the dataset is."""
from __future__ import annotations

import io
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
from services import analytics
from utils.validators import is_datetime, is_numeric

PALETTE = config.PALETTE
PLOT_CONFIG = {"displaylogo": False, "scrollZoom": True,
               "toImageButtonOptions": {"format": "png", "filename": "chart", "scale": 2}}
MAX_SERIES = 8


def theme() -> str:
    return st.session_state.get("plotly_theme", "plotly_white")


def style(fig: go.Figure, title: str = "", height: int = 440) -> go.Figure:
    fig.update_layout(template=theme(), title=dict(text=title, x=0.01, font=dict(size=16)), height=height,
                      margin=dict(l=20, r=20, t=55, b=20), colorway=PALETTE,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                      font=dict(family="Inter, Segoe UI, sans-serif"))
    return fig


def show(fig: go.Figure, key: Optional[str] = None) -> None:
    st.plotly_chart(fig, use_container_width=True, config=PLOT_CONFIG, key=key)


# --------------------------------------------------------------------- simple, dashboard-level charts
def trend_chart(ts: pd.DataFrame, title: str, height: int = 340) -> go.Figure:
    xcol, ycol = ts.columns[0], ts.columns[1]
    fig = px.area(ts, x=xcol, y=ycol)
    fig.update_traces(line_color=PALETTE[0], fillcolor="rgba(79,70,229,.15)")
    return style(fig, title, height)


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str, horizontal: bool = False, height: int = 340) -> go.Figure:
    fig = px.bar(df, x=y if horizontal else x, y=x if horizontal else y, orientation="h" if horizontal else "v")
    fig.update_traces(marker_color=PALETTE[0])
    if horizontal:
        fig.update_yaxes(autorange="reversed")
    return style(fig, title, height)


def donut(labels: List[str], values: List[float], title: str, height: int = 340) -> go.Figure:
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.6, sort=False))
    return style(fig, title, height)


def correlation_heatmap(corr: pd.DataFrame, title: str = "Correlation matrix") -> go.Figure:
    fig = px.imshow(corr, text_auto=".2f", zmin=-1, zmax=1, aspect="auto", color_continuous_scale="RdBu_r")
    return style(fig, title, height=max(380, 38 * len(corr) + 160))


def histogram(series: pd.Series, name: str, bins: int = 60, height: int = 340) -> go.Figure:
    counts, edges = _hist(series, bins)
    centers = (edges[:-1] + edges[1:]) / 2
    fig = go.Figure(go.Bar(x=centers, y=counts, marker_color=PALETTE[0], width=np.diff(edges) * 0.95))
    fig.update_layout(xaxis_title=name, yaxis_title="Records")
    return style(fig, f"Distribution — {name}", height)


def box_plot(series: pd.Series, name: str, height: int = 360) -> go.Figure:
    s = _finite(series)
    if len(s) > 100_000:
        s = s.sample(100_000, random_state=1)
    fig = go.Figure(go.Box(y=s, name=name, boxpoints="outliers", marker_color=PALETTE[0]))
    return style(fig, f"Box plot — {name}", height)


def memory_bar(mem: pd.DataFrame, height: int = 360) -> go.Figure:
    top = mem.head(15)
    fig = px.bar(top, x="Memory (MB)", y="Column", orientation="h", color="Stored dtype", color_discrete_sequence=PALETTE)
    fig.update_yaxes(autorange="reversed")
    return style(fig, "Memory footprint by column (top 15)", height)


def static_corr_png(corr: pd.DataFrame) -> bytes:
    """Matplotlib/Seaborn heatmap as PNG bytes (no kaleido needed)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
    size = max(6, 0.55 * len(corr) + 3)
    fig, ax = plt.subplots(figsize=(size, size * 0.85))
    sns.heatmap(corr, annot=len(corr) <= 15, fmt=".2f", cmap="RdBu_r", vmin=-1, vmax=1, square=False, ax=ax,
                cbar_kws={"shrink": .8})
    ax.set_title("Correlation matrix")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160)
    plt.close(fig)
    return buf.getvalue()


# --------------------------------------------------------------------- helpers
def _finite(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce").astype("float64")
    return x[np.isfinite(x)]


def _hist(s: pd.Series, bins: int) -> Tuple[np.ndarray, np.ndarray]:
    x = _finite(s).to_numpy()
    if x.size == 0:
        raise ValueError("No finite numeric values to plot.")
    return np.histogram(x, bins=bins)


def _prep_x(df: pd.DataFrame, x: str, top_n: int, notes: List[str]) -> pd.DataFrame:
    """Bucket dates, bin dense numerics, and keep the top-N categories so charts stay light and readable."""
    s = df[x]
    if is_datetime(s):
        level = analytics.auto_time_level(s)
        notes.append({"D": "daily", "W": "weekly", "M": "monthly", "Y": "yearly"}[level] + " buckets")
        return df.assign(**{x: analytics.bucket_datetime(s, level)})
    if is_numeric(s) and s.nunique() > top_n:
        nb = min(top_n, 40)
        cut = pd.cut(s, bins=nb)
        mids = [iv.mid for iv in cut.cat.categories]
        notes.append(f"{nb} numeric bins")
        return df.assign(**{x: cut.cat.rename_categories(mids).astype("float64")})
    if not is_numeric(s) and s.nunique() > top_n:
        notes.append(f"top {top_n} categories")
        return analytics.limit_categories(df, x, top_n)
    return df


def _series_col(df: pd.DataFrame, group: Optional[str], color: Optional[str], x: str, notes: List[str]) -> Tuple[pd.DataFrame, Optional[str]]:
    col = group or color
    if not col or col == x:
        return df, None
    if is_numeric(df[col]) and df[col].nunique() > MAX_SERIES:
        notes.append(f"'{col}' ignored as series (numeric, too many values)")
        return df, None
    if df[col].nunique() > MAX_SERIES:
        notes.append(f"top {MAX_SERIES} '{col}' values")
        df = analytics.limit_categories(df, col, MAX_SERIES)
    return df, col


# --------------------------------------------------------------------- main builder
def build_chart(df: pd.DataFrame, kind: str, x: Optional[str], y: Optional[str], group: Optional[str],
                color: Optional[str], agg: str, top_n: int = 30, freq: str = "Auto",
                bins: int = 60) -> Tuple[go.Figure, str]:
    """Build a figure from user selections. Returns (figure, note). Raises ValueError with a friendly message."""
    if df.empty:
        raise ValueError("No rows left after filtering.")
    notes: List[str] = []
    n_in = len(df)

    # ---------------- raw-distribution charts
    if kind == "Histogram":
        col = x or y
        if not col or not is_numeric(df[col]):
            raise ValueError("Histogram needs a numeric X column.")
        sc = group or color
        if sc and sc != col and df[sc].nunique() <= MAX_SERIES + 40:
            d = analytics.limit_categories(df, sc, 6)
            edges = np.histogram_bin_edges(_finite(d[col]).to_numpy(), bins=bins)
            frames = []
            for name, g in d.groupby(sc, observed=True):
                cnt, _ = np.histogram(_finite(g[col]).to_numpy(), bins=edges)
                frames.append(pd.DataFrame({col: (edges[:-1] + edges[1:]) / 2, "Records": cnt, sc: str(name)}))
            fig = px.bar(pd.concat(frames), x=col, y="Records", color=sc, barmode="overlay", opacity=.75)
        else:
            cnt, edges = _hist(df[col], bins)
            fig = px.bar(pd.DataFrame({col: (edges[:-1] + edges[1:]) / 2, "Records": cnt}), x=col, y="Records")
        return style(fig, f"Histogram — {col}"), f"{n_in:,} rows binned into {bins} bins (computed before plotting)."

    if kind == "Box Plot":
        yy = y or (x if x and is_numeric(df[x]) else None)
        xx = x if (y and x) else None
        if not yy or not is_numeric(df[yy]):
            raise ValueError("Box plot needs a numeric Y column.")
        d = df[[c for c in {xx, yy, color} if c]]
        if xx and not is_numeric(d[xx]):
            d = analytics.limit_categories(d, xx, 15)
        if len(d) > 100_000:
            d = d.sample(100_000, random_state=1)
            notes.append("sampled 100,000 rows")
        fig = px.box(d, x=xx, y=yy, color=color if color != xx else None, points="outliers")
        return style(fig, f"Box plot — {yy}" + (f" by {xx}" if xx else "")), "; ".join(notes) or f"{len(d):,} rows."

    if kind == "Scatter Plot":
        if not x or not y or not is_numeric(df[x]) or not is_numeric(df[y]):
            raise ValueError("Scatter plot needs numeric X and Y columns.")
        sc = color or group
        d = df[[c for c in {x, y, sc} if c]].replace([np.inf, -np.inf], np.nan).dropna(subset=[x, y])
        if sc and not is_numeric(d[sc]) and d[sc].nunique() > MAX_SERIES:
            d = analytics.limit_categories(d, sc, MAX_SERIES)
        if len(d) > config.MAX_CHART_POINTS:
            d = d.sample(config.MAX_CHART_POINTS, random_state=1)
            notes.append(f"showing a random sample of {config.MAX_CHART_POINTS:,} of {n_in:,} points")
        fig = px.scatter(d, x=x, y=y, color=sc, opacity=.6)
        return style(fig, f"{y} vs {x}"), "; ".join(notes) or f"{len(d):,} points."

    if kind == "Heatmap":
        sc = group or color
        if x and sc and x != sc and not is_numeric(df[x]) and not is_numeric(df[sc]):
            d = analytics.limit_categories(analytics.limit_categories(df, x, 30), sc, 30)
            agg_df, val = analytics.aggregate(d, [sc, x], y, agg)
            pivot = agg_df.pivot(index=sc, columns=x, values=val)
            fig = px.imshow(pivot, aspect="auto", color_continuous_scale="Viridis", text_auto=".3s" if pivot.size <= 400 else False)
            return style(fig, f"{val} — {sc} × {x}", 460), "Aggregated cross-tab (max 30×30)."
        corr, n = analytics.correlation_matrix(df)
        if corr.empty:
            raise ValueError("Heatmap needs two categorical columns (X and Group By) or at least two numeric columns.")
        return correlation_heatmap(corr), f"Correlation heatmap on {n:,} rows (select X and Group By categorical columns for a cross-tab)."

    # ---------------- aggregated charts
    if kind in ("Bar Chart", "Line Chart", "Area Chart", "Pie Chart", "Treemap", "Sunburst", "Time Series"):
        if not x:
            raise ValueError("Please select an X axis column.")
        if kind == "Time Series" and not is_datetime(df[x]):
            raise ValueError("Time Series needs a date/time column on the X axis.")

        if kind == "Time Series":
            sc_df, sc = _series_col(df, group, color, x, notes)
            rule = None if freq == "Auto" else freq
            level = {"Daily": "D", "Weekly": "W", "Monthly": "M", "Yearly": "Y"}.get(freq) or analytics.auto_time_level(sc_df[x])
            d = sc_df.assign(**{x: analytics.bucket_datetime(sc_df[x], level)})
            keys = [x] + ([sc] if sc else [])
            agg_df, val = analytics.aggregate(d.dropna(subset=[x]), keys, y, agg)
            fig = px.line(agg_df.sort_values(x), x=x, y=val, color=sc)
            fig.update_xaxes(rangeslider_visible=True)
            notes.append({"D": "daily", "W": "weekly", "M": "monthly", "Y": "yearly"}[level] + " buckets")
            return style(fig, f"{val} over time", 480), "; ".join(notes)

        if kind in ("Treemap", "Sunburst"):
            if x and is_numeric(df[x]) and df[x].nunique() > top_n:
                raise ValueError(f"{kind} needs a categorical X column (this numeric column has too many distinct values).")
            d = analytics.limit_categories(df, x, top_n) if not is_datetime(df[x]) else df
            sc = group or color
            if sc and sc != x and not is_numeric(d[sc]):
                d = analytics.limit_categories(d, sc, MAX_SERIES)
                keys, path = [sc, x], [sc, x]
            else:
                keys, path = [x], [x]
            agg_df, val = analytics.aggregate(d, keys, y, agg)
            agg_df = agg_df[agg_df[val] > 0].copy()
            for p in path:
                agg_df[p] = agg_df[p].astype(str)
            fn = px.treemap if kind == "Treemap" else px.sunburst
            fig = fn(agg_df, path=path, values=val, color=val, color_continuous_scale="Blues")
            return style(fig, f"{kind} — {val}", 500), f"{len(agg_df):,} segments."

        d = _prep_x(df, x, top_n, notes)
        d, sc = _series_col(d, group, color, x, notes)
        if kind == "Pie Chart":
            sc = None
        keys = [x] + ([sc] if sc else [])
        agg_df, val = analytics.aggregate(d, keys, y, agg)
        if agg_df.empty:
            raise ValueError("No data left after aggregation (all selected values are missing).")
        categorical_x = not (is_numeric(agg_df[x]) or is_datetime(agg_df[x]))
        if kind in ("Bar Chart", "Pie Chart") and categorical_x:
            order = agg_df.groupby(x, observed=True)[val].sum().sort_values(ascending=False).index.astype(str)
            agg_df[x] = pd.Categorical(agg_df[x].astype(str), categories=list(order), ordered=True)
        agg_df = agg_df.sort_values(x)
        if kind == "Bar Chart":
            fig = px.bar(agg_df, x=x, y=val, color=sc, barmode="group")
        elif kind == "Line Chart":
            fig = px.line(agg_df, x=x, y=val, color=sc, markers=len(agg_df) < 80)
        elif kind == "Area Chart":
            fig = px.area(agg_df, x=x, y=val, color=sc)
        else:
            fig = px.pie(agg_df, names=x, values=val, hole=0.45)
        return style(fig, f"{val} by {x}"), ("; ".join(notes) + " · " if notes else "") + f"{n_in:,} rows → {len(agg_df):,} plotted values."

    raise ValueError(f"Unknown chart type '{kind}'.")
