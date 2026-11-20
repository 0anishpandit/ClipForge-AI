"""Check that the AI's quoted evidence really appears near the claimed moment."""

from __future__ import annotations

import re

# Seconds of transcript on each side of the clip that count as "nearby".
EVIDENCE_WINDOW_SECONDS = 10


def normalize_words(text: str) -> set[str]:
    """Lower-case alphanumeric words longer than two characters."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(text).lower())
    return {word for word in cleaned.split() if len(word) > 2}


def verify_evidence(evidence, rows: list[dict], start_sec: float, end_sec: float) -> float:
    """Return the fraction (0..1) of evidence words found near the moment."""
    if not evidence or len(str(evidence).strip()) < 8:
        return 0.0

    evidence_words = normalize_words(evidence)
    if len(evidence_words) < 3:
        return 0.0

    nearby_text = " ".join(
        str(row["text"])
        for row in rows
        if float(row["end_sec"]) >= start_sec - EVIDENCE_WINDOW_SECONDS
        and float(row["start_sec"]) <= end_sec + EVIDENCE_WINDOW_SECONDS
    )
    nearby_words = normalize_words(nearby_text)
    if not nearby_words:
        return 0.0

    return len(evidence_words & nearby_words) / len(evidence_words)
