"""Remove clip candidates that cover the same moment."""

from __future__ import annotations

OVERLAP_RATIO_LIMIT = 0.65
CORE_START_DELTA = 8
CORE_END_DELTA = 12


def is_duplicate(clip: dict, existing: dict) -> bool:
    overlap = max(
        0.0,
        min(clip["end_sec"], existing["end_sec"]) - max(clip["start_sec"], existing["start_sec"]),
    )
    shorter = min(clip["duration_sec"], existing["duration_sec"])
    overlap_ratio = overlap / shorter if shorter > 0 else 0
    start_delta = abs(clip["original_moment_start"] - existing["original_moment_start"])
    end_delta = abs(clip["original_moment_end"] - existing["original_moment_end"])
    return overlap_ratio >= OVERLAP_RATIO_LIMIT or (
        start_delta <= CORE_START_DELTA and end_delta <= CORE_END_DELTA
    )


def remove_duplicate_clips(clips: list[dict]) -> list[dict]:
    """Keep the best-scoring clip of every group of overlapping candidates."""
    ranked = sorted(clips, key=lambda clip: clip["quality_score"], reverse=True)
    final: list[dict] = []
    for clip in ranked:
        if not any(is_duplicate(clip, kept) for kept in final):
            final.append(clip)
    return final
