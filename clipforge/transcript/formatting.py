"""Turn transcript rows into text."""

from __future__ import annotations

from clipforge.utils import fmt_time


def format_row_for_ai(row: dict) -> str:
    """One transcript line with exact timestamps, as shown to the AI model."""
    start = float(row["start_sec"])
    end = float(row["end_sec"])
    return (
        f"[start_sec={start:.2f}, end_sec={end:.2f}, "
        f"{fmt_time(start)}-{fmt_time(end)}] {row['text']}"
    )


def to_plain_text(rows: list[dict]) -> str:
    """Human-readable transcript used for the ``.txt`` download."""
    return "\n".join(f"[{fmt_time(row['start_sec'])}] {row['text']}" for row in rows)
