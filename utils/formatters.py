"""Human-friendly number / size / duration formatting."""
from __future__ import annotations

import math


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def human_number(n, digits: int = 1) -> str:
    """10_800_000 -> '10.8M'."""
    if _bad(n):
        return "—"
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.{digits}f}{unit}"
    return f"{n:,.0f}"


def fmt_int(n) -> str:
    return "—" if _bad(n) else f"{int(round(float(n))):,}"


def human_bytes(n) -> str:
    if _bad(n):
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_seconds(s) -> str:
    if _bad(s):
        return "—"
    s = float(s)
    if s < 60:
        return f"{s:.1f} sec"
    m, sec = divmod(int(round(s)), 60)
    return f"{m}m {sec:02d}s"


def fmt_pct(x, digits: int = 2) -> str:
    return "—" if _bad(x) else f"{float(x):.{digits}f}%"


def fmt_float(x, digits: int = 2) -> str:
    return "—" if _bad(x) else f"{float(x):,.{digits}f}"
