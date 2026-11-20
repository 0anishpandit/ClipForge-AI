"""Small pure helpers used by several layers."""

from __future__ import annotations

import math


def fmt_time(seconds: float) -> str:
    """Format seconds as ``MM:SS`` or ``HH:MM:SS`` (negative values clamp to 0)."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def safe_float(value) -> float | None:
    """Convert ``value`` to a finite float, or return ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
