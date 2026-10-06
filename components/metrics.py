"""Small HTML building blocks: badges, progress bars, quality ring, pipeline stepper."""
from __future__ import annotations

from typing import Dict, List, Tuple

from utils.formatters import fmt_int, human_seconds
from utils.helpers import esc

TONES = {"excellent": "#10b981", "good": "#3b82f6", "fair": "#f59e0b", "poor": "#ef4444"}


def score_color(score: float) -> str:
    return TONES["excellent"] if score >= 90 else TONES["good"] if score >= 75 else TONES["fair"] if score >= 60 else TONES["poor"]


def badge(text: str, kind: str = "info") -> str:
    """kind: success | info | warning | danger | neutral"""
    return f"<span class='badge badge-{kind}'>{esc(text)}</span>"


def status_badge(status: str) -> str:
    kind = {"Good": "success", "Warning": "warning", "Critical": "danger"}.get(status, "neutral")
    return badge(status, kind)


def progress_bar(pct: float, label: str = "", color: str = "#4f46e5", show_value: bool = True) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    value = f"<span>{pct:.0f}%</span>" if show_value else ""
    return (f"<div class='pbar-wrap'><div class='pbar-head'><span>{esc(label)}</span>{value}</div>"
            f"<div class='pbar'><div class='pbar-fill' style='width:{pct:.1f}%;background:{color}'></div></div></div>")


def quality_ring(score: float, label: str, caption: str = "DATA QUALITY SCORE") -> str:
    color = score_color(score)
    return (f"<div class='card ring-card'><div class='ring' style='--p:{score:.1f};--c:{color}'>"
            f"<div class='ring-inner'><div class='ring-score'>{score:.1f}</div><div class='ring-sub'>/ 100</div></div></div>"
            f"<div><div class='card-title'>{esc(caption)}</div>"
            f"<span class='badge' style='background:{color}1f;color:{color}'>{esc(label)}</span></div></div>")


def dimension_bars(dims: Dict[str, float]) -> str:
    rows = "".join(
        f"<div class='pbar-wrap'><div class='pbar-head'><span>{esc(k)}</span><span>{v:.1f}%</span></div>"
        f"<div class='pbar'><div class='pbar-fill' style='width:{max(0, min(100, v)):.1f}%;background:{score_color(v)}'></div></div></div>"
        for k, v in dims.items())
    return f"<div class='card'><div class='card-title'>Quality dimensions</div>{rows}</div>"


def stage_stepper(stages: List[Tuple[str, str]]) -> str:
    """stages: [(label, state)] with state in done | running | pending"""
    items = "".join(f"<div class='stage stage-{state}'><span class='dot'></span>{esc(label)}</div>" for label, state in stages)
    return f"<div class='stepper'>{items}</div>"


def processing_monitor(pct: float, processed: int, total: int, speed: float, elapsed: float,
                       stages: List[Tuple[str, str]]) -> str:
    remaining = max(total - processed, 0)
    tiles = "".join(
        f"<div class='tile'><div class='tile-label'>{esc(label)}</div><div class='tile-value'>{esc(value)}</div></div>"
        for label, value in (
            ("Records Processed", fmt_int(processed)),
            ("Records Remaining", fmt_int(remaining)),
            ("Processing Speed", f"{fmt_int(speed)} rows/sec" if speed == speed else "—"),
            ("Execution Time", human_seconds(elapsed)),
        ))
    return (f"<div class='card'><div class='card-title'>DATA PROCESSING</div>"
            f"{progress_bar(pct, 'Pipeline progress', '#4f46e5')}<div class='tiles'>{tiles}</div>"
            f"{stage_stepper(stages)}</div>")


def section_header(title: str, subtitle: str = "") -> str:
    sub = f"<div class='section-sub'>{esc(subtitle)}</div>" if subtitle else ""
    return f"<div class='section'><div class='section-title'>{esc(title)}</div>{sub}</div>"


def insight_card(item: dict) -> str:
    icon = {"success": "✅", "info": "ℹ️", "warning": "⚠️", "critical": "🛑"}.get(item["severity"], "ℹ️")
    kind = {"success": "success", "info": "info", "warning": "warning", "critical": "danger"}.get(item["severity"], "info")
    action = f"<div class='insight-action'>➜ {esc(item['action'])}</div>" if item.get("action") else ""
    return (f"<div class='insight insight-{kind}'><div class='insight-icon'>{icon}</div><div>"
            f"<div class='insight-title'>{esc(item['title'])} {badge(item['category'], 'neutral')}</div>"
            f"<div class='insight-detail'>{esc(item['detail'])}</div>{action}</div></div>")


def hero(title: str, subtitle: str, small: bool = True) -> str:
    cls = "hero small" if small else "hero"
    return f"<div class='{cls}'><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>"
