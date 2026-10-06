# 📊 Big Data Analytics Dashboard

> **Enterprise Data Intelligence Platform** — a Streamlit application that walks through the complete big-data workflow:
> **Ingestion → Processing → Cleaning → Analysis → Visualization → Analytics → Insights → Export**

## Project Description

An enterprise-style analytics platform built with Python. It ingests CSV / Excel / JSON / Parquet files (streaming and sampling very large ones instead of loading everything), measures data quality across five dimensions, runs a chunked cleaning pipeline with a live monitor, profiles the data, builds interactive charts, finds correlations, generates plain-language insights and exports the results. Everything runs locally — no paid APIs or external AI services.

## Features

| Area | What you get |
| --- | --- |
| **Dashboard** | 8 live KPI cards (records, size, columns, processing time, quality, missing %, duplicate %, outliers), pipeline status, quality ring, top insights, overview charts |
| **Data Ingestion** | Drag-and-drop upload, load straight from a disk path (best for huge files), sample generator (10k → 2M records), load time, engine used, detected types, searchable / sortable / filterable / paginated preview |
| **Data Quality** | Completeness · Accuracy · Consistency · Uniqueness · Validity, a global 0–100 score, issue table with status badges, column-level report, outlier inspection, one-click type fixing |
| **Processing** | Live pipeline monitor (progress, records processed/remaining, rows/sec, execution time, stage badges) + cleaning tools: missing values (remove / mean / median / mode / ffill / bfill / custom), duplicates, type conversion, outliers (IQR / Z-score → cap, remove, flag), change log |
| **Exploratory Analysis** | Numerical profile (percentiles, IQR, skew, kurtosis), categorical profile, daily / weekly / monthly / yearly trends |
| **Visualization Studio** | Bar, Line, Area, Scatter, Histogram, Box, Heatmap, Pie, Treemap, Sunburst, Time Series · X / Y / Group by / Color / Aggregation / Filters. Data is binned or aggregated *before* plotting so any dataset size stays fast |
| **Big Data Stats** | Engine status, memory footprint, normality diagnostics, **SQL console** (DuckDB, SQLite fallback), optional **PySpark** and **Kafka** adapters |
| **Correlations** | Pearson / Spearman / Kendall, interactive heatmap, strongest positive / negative pairs, tested pair explorer |
| **Insights** | Rule-based findings by category with severity and recommended action. The word *significant* is used only when a test was actually run (e.g. the trend regression) |
| **Export** | Clean data as CSV / Excel / JSON / Parquet, statistics, correlations, quality report, HTML report, correlation heatmap PNG, chart HTML/PNG |

## Technologies

Python 3.11+ · Streamlit · Pandas · NumPy · **Polars** · **PyArrow** · **DuckDB** · Plotly · Matplotlib · Seaborn · SciPy · OpenPyXL
Optional: PySpark, kafka-python

## How "big data" is handled

```text
Raw Data
   ↓
Data Ingestion      Polars lazy scan → DuckDB → pandas chunks (first available engine)
   ↓                exact record count + uniform sample if rows > BDA_MAX_ROWS
Parquet             columnar, Snappy-compressed copy in data/processed/
   ↓
Polars / DuckDB     SQL + vectorised analytics
   ↓
Data Cleaning       chunked pipeline (BDA_CHUNK_SIZE rows at a time)
   ↓
Analytics → Visualization → Insights → Export
```

* Files bigger than the in-memory limit (**2,000,000 rows** by default) are streamed; the *exact* record count is shown, analysis uses a uniform sample, and the UI says so.
* Expensive estimates (quality checks on text, correlations) run on bounded samples.
* Charts never receive raw millions of points: histograms are binned in NumPy, bar/line charts are aggregated, scatter plots are capped at 50,000 points.
* If Polars / DuckDB / PyArrow cannot be installed, the app **falls back to pandas** automatically.

Environment variables: `BDA_MAX_ROWS`, `BDA_CHUNK_SIZE`, `BDA_ANALYSIS_SAMPLE`.

## Installation

```bash
cd big_data_analytics
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional integrations: `pip install -r requirements-optional.txt` (PySpark needs Java 11+).

## Usage

```bash
python -m streamlit run app.py
```

(`streamlit run app.py` also works when the Scripts folder is on your PATH.) Open http://localhost:8501, then:

1. **Data Ingestion** → upload a file, load one from disk, or generate the sample dataset.
2. **Data Quality** → read the score and issues.
3. **Processing** → press **▶ Run pipeline** (or use the cleaning tools).
4. Explore with **Exploratory Analysis**, **Visualization Studio**, **Correlations**, **Insights**, **Big Data Stats**.
5. **Export** your results.

## Project Structure

```text
big_data_analytics/
├── app.py                     # entry point, CSS, routing, global error guard
├── config.py                  # paths, limits, weights, navigation, chart types
├── requirements.txt / requirements-optional.txt
├── data/
│   ├── raw/                   # uploaded originals
│   ├── processed/             # Parquet output
│   └── sample/                # sample_transactions.csv
├── pages/                     # one render() per page (10 pages)
├── components/                # sidebar, navbar, kpi_cards, charts, tables, metrics
├── services/                  # UI-free logic: ingestion, cleaning, data_quality, processing, analytics
├── utils/                     # helpers (session + optional deps), validators, formatters
└── assets/                    # style.css, logo.png
```

Design rule: **`services/` never imports page code** and holds all the data logic, so it can be unit-tested or reused from a notebook.

## Screenshots

Add your own images to `assets/` and reference them here:

```markdown
![Dashboard](assets/screenshot_dashboard.png)
![Data Quality](assets/screenshot_quality.png)
![Visualization Studio](assets/screenshot_viz.png)
```

## Example Dataset

`data/sample/sample_transactions.csv` (5,000 rows) is included. For bigger tests use **Data Ingestion → Sample dataset** (up to 2,000,000 records). It contains deliberate flaws — missing values, exact duplicates, extreme outliers, inconsistent country spellings — so every feature has something to show.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `'streamlit' is not recognized` (Windows) | Use `python -m streamlit run app.py` |
| `pip install` fails on polars / pyarrow / duckdb | Remove that line from `requirements.txt` (or use Python 3.12/3.13). The app falls back to pandas |
| Parquet features disabled | Install `pyarrow` |
| Out of memory on a huge file | Lower **Max rows kept in memory** in the sidebar settings, or convert the file to Parquet first |
| Excel export button disabled | Excel is limited to 1,048,575 rows — export CSV or Parquet |
| Chart PNG download missing | `pip install kaleido`, or use the camera icon on the chart |
| Dates treated as text | Processing → Cleaning tools → Data types → convert to Date/Datetime |

## Notes on statistics

* Data-quality *Accuracy* is a proxy (values beyond 3×IQR fences are *potentially* wrong, not necessarily wrong).
* Correlation ≠ causation. With very large *n*, tiny effects become statistically significant — look at effect sizes.
* The SQL console is read-only and intended for local use.

## Future Improvements

* Run the Spark adapter against a real cluster and persist Kafka micro-batches as partitioned Parquet
* Scheduled pipelines and saved cleaning recipes
* Forecasting, clustering and anomaly-detection pages
* Database connectors (PostgreSQL, BigQuery, Snowflake) and authentication
* Automated test suite and CI
