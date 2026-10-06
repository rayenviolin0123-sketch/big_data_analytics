"""Central configuration for the Big Data Analytics Dashboard."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "BIG DATA ANALYTICS"
APP_TAGLINE = "Enterprise Data Intelligence Platform"

# ---- paths -------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLE_DIR = DATA_DIR / "sample"
ASSETS_DIR = BASE_DIR / "assets"

# ---- big-data behaviour (override with environment variables) ----------
# Rows kept in memory for interactive analysis. Larger files are streamed and
# systematically sampled; the exact record count is still reported.
MAX_ROWS_IN_MEMORY = int(os.getenv("BDA_MAX_ROWS", 2_000_000))
CHUNK_SIZE = int(os.getenv("BDA_CHUNK_SIZE", 250_000))
ANALYSIS_SAMPLE = int(os.getenv("BDA_ANALYSIS_SAMPLE", 200_000))  # for costly estimates
MAX_CHART_POINTS = 50_000
EXCEL_MAX_ROWS = 1_048_575

CSV_EXTENSIONS = {".csv", ".tsv", ".txt"}
SUPPORTED_EXTENSIONS = CSV_EXTENSIONS | {".xlsx", ".xls", ".json", ".jsonl", ".parquet"}
UPLOAD_TYPES = ["csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet"]

# ---- data quality ------------------------------------------------------
QUALITY_WEIGHTS = {
    "Completeness": 0.25,
    "Accuracy": 0.20,
    "Consistency": 0.15,
    "Uniqueness": 0.20,
    "Validity": 0.20,
}

# ---- navigation --------------------------------------------------------
NAV_ITEMS = [
    ("Dashboard", "🏠"),
    ("Data Ingestion", "📥"),
    ("Data Quality", "🛡️"),
    ("Processing", "⚙️"),
    ("Exploratory Analysis", "🔍"),
    ("Visualization Studio", "📈"),
    ("Big Data Stats", "🧮"),
    ("Correlations", "🔗"),
    ("Insights", "💡"),
    ("Export", "💾"),
]

CHART_TYPES = ["Bar Chart", "Line Chart", "Area Chart", "Scatter Plot", "Histogram", "Box Plot",
               "Heatmap", "Pie Chart", "Treemap", "Sunburst", "Time Series"]
AGGREGATIONS = {"Sum": "sum", "Mean": "mean", "Median": "median", "Count": "count",
                "Min": "min", "Max": "max", "Unique Count": "nunique"}

PALETTE = ["#4f46e5", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]
