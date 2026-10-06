"""Streamlit session-state access for the working dataset, cleaning recipe and pipeline results."""
from __future__ import annotations

from typing import List, Optional, Tuple

import pandas as pd
import streamlit as st

import config
from services import data_quality
from services.cleaning import Step
from services.ingestion import IngestResult


def set_dataset(df: pd.DataFrame, meta: IngestResult) -> None:
    ss = st.session_state
    ss["df"] = df
    ss["df_original"] = df.copy() if len(df) <= config.MAX_IN_MEMORY_ROWS else df
    ss["meta"] = meta
    ss["steps"] = []
    ss["history"] = []
    ss["pipeline"] = None
    ss["data_version"] = ss.get("data_version", 0) + 1
    ss.pop("_quality", None)
    ss.pop("last_fig", None)


def get_df() -> Optional[pd.DataFrame]:
    return st.session_state.get("df")


def get_meta() -> Optional[IngestResult]:
    return st.session_state.get("meta")


def get_steps() -> List[Step]:
    return st.session_state.setdefault("steps", [])


def require_df() -> Optional[pd.DataFrame]:
    df = get_df()
    if df is None or df.empty:
        st.info("📂 No dataset loaded yet. Go to **Data Ingestion** to upload a file or load the sample dataset.")
        return None
    return df


def update_df(df: pd.DataFrame, step: Optional[Step] = None, message: str = "") -> None:
    """Replace the working frame, record the cleaning step and invalidate cached results."""
    ss = st.session_state
    ss["df"] = df.reset_index(drop=True)
    ss["data_version"] = ss.get("data_version", 0) + 1
    ss.pop("_quality", None)
    ss["pipeline"] = None                       # the recipe changed -> the processed output is stale
    if step is not None:
        get_steps().append(step)
    if message:
        ss.setdefault("history", []).append(message)


def reset_dataset() -> None:
    ss = st.session_state
    if ss.get("df_original") is not None:
        ss["df"] = ss["df_original"].copy()
        ss["steps"], ss["history"], ss["pipeline"] = [], [], None
        ss["data_version"] = ss.get("data_version", 0) + 1
        ss.pop("_quality", None)


def undo_last_step() -> bool:
    """Rebuild the working frame by replaying all steps except the last one on the original."""
    from services.cleaning import replay
    steps = get_steps()
    if not steps or st.session_state.get("df_original") is None:
        return False
    remaining = steps[:-1]
    st.session_state["df"] = replay(st.session_state["df_original"].copy(), remaining).reset_index(drop=True)
    st.session_state["steps"] = remaining
    st.session_state["history"] = st.session_state.get("history", [])[:len(remaining)]
    st.session_state["pipeline"] = None
    st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
    st.session_state.pop("_quality", None)
    return True


def get_quality() -> Optional[data_quality.QualityReport]:
    """Quality report for the working frame, cached per data version."""
    df = get_df()
    if df is None or df.empty:
        return None
    version = st.session_state.get("data_version", 0)
    cached: Optional[Tuple[int, data_quality.QualityReport]] = st.session_state.get("_quality")
    if cached and cached[0] == version:
        return cached[1]
    report = data_quality.assess(df)
    st.session_state["_quality"] = (version, report)
    return report


def stage_status() -> dict:
    """Four-stage pipeline status used by the navbar and the Processing page."""
    df, steps, pipe = get_df(), get_steps(), st.session_state.get("pipeline")
    loaded = df is not None
    cleaned = loaded and len(steps) > 0
    processed = loaded and pipe is not None
    ready = loaded and (processed or not steps)
    return {"DATA LOADED": loaded, "DATA CLEANED": cleaned, "DATA PROCESSED": processed, "ANALYSIS READY": ready}
