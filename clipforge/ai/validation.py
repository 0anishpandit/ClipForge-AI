"""Validate one AI clip candidate and expand it to the requested length."""

from __future__ import annotations

from clipforge.ai.evidence import verify_evidence
from clipforge.config import DEFAULT_TIMESTAMP_TOLERANCE
from clipforge.utils import fmt_time, safe_float

# Rejection reasons (also the keys of the analysis rejection counters).
INVALID_STRUCTURE = "invalid_structure"
INVALID_TIMESTAMPS = "invalid_timestamps"
INVALID_DURATION = "invalid_duration"
OUTSIDE_CHUNK = "outside_chunk"
UNSUPPORTED_EVIDENCE = "unsupported_evidence"
GENERIC_OR_INCOMPLETE = "generic_or_incomplete"

REJECTION_REASONS = (
    INVALID_STRUCTURE, INVALID_TIMESTAMPS, UNSUPPORTED_EVIDENCE,
    INVALID_DURATION, OUTSIDE_CHUNK, GENERIC_OR_INCOMPLETE,
)

MIN_EVIDENCE_MATCH = 0.35
MIN_CORE_SECONDS = 2

GENERIC_TITLES = {
    "unexpected event during gameplay",
    "unexpected gameplay moment",
    "interesting gameplay moment",
    "funny gaming moment",
    "amazing gaming moment",
    "unexpected moment",
}


def validate_clip(
    clip,
    chunk: dict,
    rows: list[dict],
    video_duration: float,
    min_duration: float,
    max_duration: float,
    tolerance: float = DEFAULT_TIMESTAMP_TOLERANCE,
) -> tuple[dict | None, str | None]:
    """Return ``(validated_clip, None)`` or ``(None, rejection_reason)``.

    The validated clip's window is the AI's core moment, expanded evenly on
    both sides (and shifted to stay inside the video) to reach ``min_duration``.
    """
    if not isinstance(clip, dict):
        return None, INVALID_STRUCTURE

    core_start = safe_float(clip.get("start_sec"))
    core_end = safe_float(clip.get("end_sec"))
    if core_start is None or core_end is None:
        return None, INVALID_TIMESTAMPS
    if core_start < 0 or core_end <= core_start:
        return None, INVALID_TIMESTAMPS

    core_duration = core_end - core_start
    if core_duration < MIN_CORE_SECONDS or core_duration > max_duration:
        return None, INVALID_DURATION

    chunk_start = float(chunk["start_sec"])
    chunk_end = float(chunk["end_sec"])
    if core_start < chunk_start - tolerance or core_start > chunk_end + tolerance:
        return None, OUTSIDE_CHUNK
    if core_end > video_duration + tolerance:
        return None, INVALID_TIMESTAMPS

    core_start = max(0.0, core_start)
    core_end = min(video_duration, core_end)
    core_duration = core_end - core_start

    evidence = str(clip.get("evidence", "")).strip()
    evidence_match = verify_evidence(evidence, rows, core_start, core_end)
    if evidence_match < MIN_EVIDENCE_MATCH:
        return None, UNSUPPORTED_EVIDENCE

    title = str(clip.get("title", "")).strip()
    hook = str(clip.get("hook", "")).strip()
    reason = str(clip.get("reason", "")).strip()
    if len(title) < 5 or len(hook) < 5 or len(reason) < 8:
        return None, GENERIC_OR_INCOMPLETE
    if title.lower() in GENERIC_TITLES:
        return None, GENERIC_OR_INCOMPLETE

    # Expand around the core moment up to the minimum duration.
    target = min(max(min_duration, core_duration), max_duration, video_duration)
    extra = target - core_duration
    final_start = core_start - extra / 2
    final_end = core_end + extra / 2

    if final_start < 0:
        final_end += -final_start
        final_start = 0.0
    if final_end > video_duration:
        final_start -= final_end - video_duration
        final_end = video_duration
    final_start = max(0.0, final_start)
    final_duration = final_end - final_start
    if final_duration < MIN_CORE_SECONDS:
        return None, INVALID_DURATION

    ai_score = safe_float(clip.get("score", 5))
    if ai_score is None:
        ai_score = 5
    ai_score = max(1, min(10, ai_score))
    quality_score = min(10, ai_score * 0.75 + evidence_match * 2.5)

    return {
        "start_sec": round(final_start, 2),
        "end_sec": round(final_end, 2),
        "start": fmt_time(final_start),
        "end": fmt_time(final_end),
        "duration_sec": round(final_duration, 2),
        "title": title,
        "hook": hook,
        "reason": reason,
        "evidence": evidence,
        "score": round(ai_score, 1),
        "evidence_match": round(evidence_match * 100, 1),
        "quality_score": round(quality_score, 2),
        "original_moment_start": round(core_start, 2),
        "original_moment_end": round(core_end, 2),
    }, None
