"""Export: cleaned data (CSV/Excel/JSON/Parquet), analysis tables, report and charts."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from components import charts
from components.metrics import hero
from services import analytics, data_quality, ingestion
from utils import helpers
from utils.formatters import fmt_int, human_bytes
from utils.helpers import esc


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _excel(df: pd.DataFrame) -> bytes:
    out = df.copy()
    for c in out.select_dtypes(include=["datetimetz"]).columns:
        out[c] = out[c].dt.tz_localize(None)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        out.to_excel(w, index=False, sheet_name="Clean data")
    return buf.getvalue()


def _parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    try:
        df.to_parquet(buf, index=False, compression="snappy")
    except Exception:  # noqa: BLE001 - mixed-type object columns
        fixed = df.copy()
        for c in fixed.columns:
            if pd.api.types.is_object_dtype(fixed[c]):
                fixed[c] = fixed[c].astype("string")
        buf = io.BytesIO()
        fixed.to_parquet(buf, index=False, compression="snappy")
    return buf.getvalue()


def _html_report(df: pd.DataFrame, rep, meta: dict, insights: list) -> bytes:
    rows = "".join(f"<tr><td>{esc(r['Check'])}</td><td>{int(r['Count']):,}</td><td>{r['Percent']:.2f}%</td><td>{esc(r['Status'])}</td></tr>"
                   for _, r in rep.issues.iterrows())
    dims = "".join(f"<li>{esc(k)}: <b>{v:.1f}</b></li>" for k, v in rep.dimensions.items())
    ins = "".join(f"<li><b>{esc(i['title'])}</b> — {esc(i['detail'])}</li>" for i in insights)
    stats = analytics.numeric_summary(df).round(3).to_html(index=False, border=0)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Big Data Analytics Report</title>
<style>body{{font-family:Inter,Segoe UI,sans-serif;max-width:980px;margin:2rem auto;color:#0f172a;padding:0 1rem}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}}td,th{{border-bottom:1px solid #e5e9f2;padding:.4rem .6rem;text-align:left}}
h1{{color:#312e81}}.score{{font-size:2.6rem;font-weight:800;color:#4f46e5}}</style></head><body>
<h1>Big Data Analytics Report</h1><p>Dataset <b>{esc(meta.get('name', ''))}</b> · generated {datetime.now():%Y-%m-%d %H:%M}</p>
<p>Records: <b>{helpers.total_records():,}</b> · Columns: <b>{df.shape[1]}</b> · Analysed rows: <b>{len(df):,}</b></p>
<div class="score">{rep.score:.1f} / 100 <small>({esc(rep.label)})</small></div><ul>{dims}</ul>
<h2>Issues</h2><table><tr><th>Check</th><th>Count</th><th>Share</th><th>Status</th></tr>{rows}</table>
<h2>Insights</h2><ul>{ins}</ul><h2>Numerical summary</h2>{stats}</body></html>""".encode("utf-8")


def render() -> None:
    st.markdown(hero("💾 Export", "Download clean data, analysis tables, a report and charts"), unsafe_allow_html=True)
    df = helpers.require_data()
    if df is None:
        return
    meta = helpers.get_meta()
    base = Path(meta.get("name", "dataset")).stem
    stamp = f"{datetime.now():%Y%m%d}"

    st.markdown("### Clean dataset")
    st.caption(f"{fmt_int(len(df))} rows × {df.shape[1]} columns currently in the working data"
               + (" (a uniform sample of the source file)." if meta.get("sampled") else "."))
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Prepare CSV", key="prep_csv", use_container_width=True):
        st.session_state["_exp_csv"] = _csv(df)
    if c2.button("Prepare Excel", key="prep_xlsx", use_container_width=True, disabled=len(df) > config.EXCEL_MAX_ROWS):
        with st.spinner("Building Excel file …"):
            st.session_state["_exp_xlsx"] = _excel(df)
    if c3.button("Prepare JSON", key="prep_json", use_container_width=True):
        st.session_state["_exp_json"] = df.to_json(orient="records", date_format="iso").encode("utf-8")
    if c4.button("Prepare Parquet", key="prep_pq", use_container_width=True, disabled=not helpers.HAS_PYARROW):
        st.session_state["_exp_pq"] = _parquet(df)
    if len(df) > config.EXCEL_MAX_ROWS:
        st.caption(f"Excel is limited to {config.EXCEL_MAX_ROWS:,} rows — use CSV or Parquet for this dataset.")
    for key, label, name, mime in (
        ("_exp_csv", "⬇️ Download CSV", f"{base}_clean_{stamp}.csv", "text/csv"),
        ("_exp_xlsx", "⬇️ Download Excel", f"{base}_clean_{stamp}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("_exp_json", "⬇️ Download JSON", f"{base}_clean_{stamp}.json", "application/json"),
        ("_exp_pq", "⬇️ Download Parquet", f"{base}_clean_{stamp}.parquet", "application/octet-stream"),
    ):
        if key in st.session_state:
            st.download_button(f"{label} ({human_bytes(len(st.session_state[key]))})", st.session_state[key], name, mime, key=f"dl{key}")

    if helpers.HAS_PYARROW and st.button("💽 Save Parquet to data/processed/ on this machine", key="save_pq"):
        path = ingestion.write_parquet(df, base)
        st.success(f"Saved to `{path}`") if path else st.error("⚠️ Could not write the Parquet file.")

    st.markdown("### Analysis")
    a1, a2, a3, a4 = st.columns(4)
    summary = analytics.numeric_summary(df)
    rep = helpers.memo("quality", lambda: data_quality.assess(df))
    corr, _ = analytics.correlation_matrix(df, st.session_state.get("corr_method", "Pearson").lower())
    insights = helpers.memo("insights", lambda: analytics.generate_insights(df, rep, st.session_state.get("corr_threshold", 0.6)))
    if summary.empty:
        a1.info("No numeric columns.")
    else:
        a1.download_button("⬇️ Statistics CSV", _csv(summary), f"{base}_statistics.csv", "text/csv", use_container_width=True)
    if corr.empty:
        a2.info("Need 2+ numeric columns.")
    else:
        a2.download_button("⬇️ Correlation CSV", corr.round(6).reset_index().rename(columns={"index": "variable"}).pipe(_csv),
                           f"{base}_correlations.csv", "text/csv", use_container_width=True)
    a3.download_button("⬇️ Quality report CSV", _csv(rep.issues), f"{base}_quality.csv", "text/csv", use_container_width=True)
    a4.download_button("⬇️ HTML report", _html_report(df, rep, meta, insights), f"{base}_report.html", "text/html", use_container_width=True)

    st.markdown("### Charts")
    if not corr.empty:
        st.download_button("⬇️ Correlation heatmap (PNG)", charts.static_corr_png(corr), f"{base}_correlation.png", "image/png")
    fig = st.session_state.get("last_fig")
    if fig is None:
        st.info("Build a chart in the Visualization Studio and it will be available here.")
        return
    charts.show(fig, key="export_fig")
    st.download_button("⬇️ Chart (interactive HTML)", fig.to_html(include_plotlyjs="cdn").encode("utf-8"), f"{base}_chart.html", "text/html")
    try:
        st.download_button("⬇️ Chart (PNG)", fig.to_image(format="png", scale=2), f"{base}_chart.png", "image/png")
    except Exception:  # noqa: BLE001 - kaleido is optional
        st.caption("PNG export of Plotly charts needs the optional `kaleido` package. The camera icon on any chart also saves a PNG.")
