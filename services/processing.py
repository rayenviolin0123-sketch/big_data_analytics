"""Chunked processing pipeline + optional PySpark / Kafka integration layer.

Architecture::

    Raw data → Ingestion → Parquet → Polars/DuckDB/pandas → Cleaning → Analytics → Visualization

The pipeline below works on any machine (pure pandas). PySpark and Kafka are *optional*
adapters used only when those packages are installed.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import config
from services import cleaning, data_quality, ingestion
from utils.helpers import HAS_KAFKA, HAS_PYSPARK
from utils.validators import is_numeric

# progress callback: (percent 0-100, records_processed, total_records, elapsed_seconds, stage_index)
ProgressFn = Callable[[float, int, int, float, int], None]


@dataclass
class PipelineOptions:
    standardize_text: bool = True
    drop_duplicates: bool = True
    fill_missing: bool = True
    cap_outliers: bool = False
    outlier_method: str = "IQR"
    write_parquet: bool = True


def run_pipeline(df: pd.DataFrame, opts: PipelineOptions, name: str = "dataset",
                 progress: Optional[ProgressFn] = None) -> tuple[pd.DataFrame, dict]:
    """Run the cleaning/processing pipeline. Returns (new frame, report)."""
    t0 = time.perf_counter()
    n = len(df)
    report: dict = {"rows_in": n, "cols": df.shape[1], "options": opts.__dict__.copy()}

    def tick(pct, processed, stage):
        if progress:
            progress(min(pct, 100.0), min(processed, n), n, time.perf_counter() - t0, stage)

    # ---- stage 1: chunked text standardisation (streaming-friendly, per-chunk memory)
    cleaned = df
    changed = 0
    if opts.standardize_text and n:
        parts = []
        for start in range(0, n, config.CHUNK_SIZE):
            chunk, c = cleaning.standardize_text(df.iloc[start:start + config.CHUNK_SIZE])
            parts.append(chunk)
            changed += c
            tick(5 + 50 * min(start + config.CHUNK_SIZE, n) / n, start + config.CHUNK_SIZE, 1)
        cleaned = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    report["text_cells_standardized"] = changed
    tick(55, n, 1)

    # ---- stage 2: global cleaning steps (need whole-column statistics)
    removed = 0
    if opts.drop_duplicates:
        cleaned, removed = cleaning.drop_duplicates(cleaned)
    report["duplicates_removed"] = removed
    tick(65, n, 1)

    filled = 0
    if opts.fill_missing:
        cleaned, filled = cleaning.fill_missing_auto(cleaned)
    report["missing_filled"] = filled
    tick(75, n, 1)

    capped = 0
    if opts.cap_outliers:
        for col in [c for c in cleaned.columns if is_numeric(cleaned[c])]:
            before = cleaned[col]
            cleaned, _ = cleaning.handle_outliers(cleaned, col, opts.outlier_method, "Cap (winsorize)")
            capped += int((before != cleaned[col]).sum())
    report["outliers_capped"] = capped
    t_clean = time.perf_counter() - t0
    report["clean_seconds"] = t_clean
    tick(85, n, 2)

    # ---- stage 3: persist as Parquet (columnar, compressed)
    pq_path = None
    if opts.write_parquet:
        pq_path = ingestion.write_parquet(cleaned, name)
    report["parquet_path"] = str(pq_path) if pq_path else None
    report["parquet_bytes"] = pq_path.stat().st_size if pq_path and pq_path.exists() else None
    tick(93, n, 2)

    # ---- stage 4: pre-compute analysis artefacts
    quality = data_quality.assess(cleaned)
    report["quality"] = quality
    total = time.perf_counter() - t0
    report.update({"rows_out": len(cleaned), "seconds": total, "rows_per_sec": n / total if total > 0 else float("nan")})
    tick(100, n, 3)
    return cleaned, report


# ------------------------------------------------------------------ optional: PySpark
def spark_aggregate(path: str | Path, group_col: str, value_col: Optional[str] = None,
                    agg: str = "sum", limit: int = 1000) -> pd.DataFrame:
    """Distributed group-by on a Parquet/CSV file using a local Spark session (requires pyspark + Java)."""
    if not HAS_PYSPARK:
        raise ImportError("PySpark is not installed (pip install pyspark; Java 11+ required).")
    from pyspark.sql import SparkSession, functions as F
    spark = (SparkSession.builder.master("local[*]").appName("BigDataAnalytics")
             .config("spark.ui.showConsoleProgress", "false").getOrCreate())
    p = str(path)
    sdf = spark.read.parquet(p) if p.endswith(".parquet") else \
        spark.read.option("header", True).option("inferSchema", True).csv(p)
    fn = {"sum": F.sum, "mean": F.avg, "min": F.min, "max": F.max, "count": F.count}[agg]
    target = fn(value_col) if (value_col and agg != "count") else F.count(F.lit(1))
    return sdf.groupBy(group_col).agg(target.alias("value")).orderBy(F.desc("value")).limit(limit).toPandas()


# ------------------------------------------------------------------ optional: Kafka
def kafka_consume_batch(topic: str, bootstrap_servers: str = "localhost:9092",
                        max_messages: int = 1000, timeout_ms: int = 5000) -> pd.DataFrame:
    """Read up to ``max_messages`` JSON messages from a Kafka topic into a DataFrame (requires kafka-python)."""
    if not HAS_KAFKA:
        raise ImportError("kafka-python is not installed (pip install kafka-python).")
    from kafka import KafkaConsumer
    consumer = KafkaConsumer(topic, bootstrap_servers=bootstrap_servers, auto_offset_reset="earliest",
                             consumer_timeout_ms=timeout_ms, group_id=None,
                             value_deserializer=lambda b: json.loads(b.decode("utf-8")))
    rows = []
    try:
        for msg in consumer:
            rows.append(msg.value)
            if len(rows) >= max_messages:
                break
    finally:
        consumer.close()
    return pd.json_normalize(rows) if rows else pd.DataFrame()


SPARK_SNIPPET = '''from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.master("local[*]").appName("BigDataAnalytics").getOrCreate()
sdf = spark.read.parquet("data/processed/your_dataset.parquet")
(sdf.groupBy("country")
    .agg(F.sum("revenue").alias("total_revenue"))
    .orderBy(F.desc("total_revenue"))
    .show(10))'''

KAFKA_SNIPPET = '''from kafka import KafkaConsumer
import json, pandas as pd

consumer = KafkaConsumer("orders", bootstrap_servers="localhost:9092",
                         auto_offset_reset="earliest", consumer_timeout_ms=5000,
                         value_deserializer=lambda b: json.loads(b.decode()))
df = pd.DataFrame([m.value for m in consumer])   # micro-batch → analytics pipeline'''
