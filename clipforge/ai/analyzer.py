"""Full highlight-detection pipeline: chunk -> ask AI -> validate -> dedupe -> rank."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Protocol

from clipforge.ai.dedup import remove_duplicate_clips
from clipforge.ai.prompts import build_system_prompt, build_user_prompt
from clipforge.ai.validation import REJECTION_REASONS, validate_clip
from clipforge.config import (
    DEFAULT_CHUNK_OVERLAP_SECONDS,
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_TIMESTAMP_TOLERANCE,
)
from clipforge.errors import AnalysisError, ClipForgeError
from clipforge.transcript.chunking import split_into_chunks
from clipforge.utils import fmt_time

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]


class ChatClient(Protocol):
    """Anything that can answer a prompt with a ``{"clips": [...]}`` dict."""

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict: ...


@dataclass
class AnalysisResult:
    clips: list[dict]
    chunks_total: int
    chunks_failed: int
    candidates: int
    rejections: dict[str, int] = field(default_factory=dict)


def analyze_transcript(
    rows: list[dict],
    client: ChatClient,
    clip_count: int,
    min_duration: float,
    max_duration: float,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    overlap_seconds: float = DEFAULT_CHUNK_OVERLAP_SECONDS,
    tolerance: float = DEFAULT_TIMESTAMP_TOLERANCE,
    progress_callback: ProgressCallback | None = None,
) -> AnalysisResult:
    """Find up to ``clip_count`` highlight clips in ``rows``.

    Raises ``AnalysisError`` if no usable clip results, or if every request to
    the model failed (in which case the underlying error is reported).
    """
    if not rows:
        raise ValueError("No transcript available.")
    if min_duration >= max_duration:
        raise ValueError("Maximum duration must exceed minimum duration.")

    video_duration = max(float(row["end_sec"]) for row in rows)
    chunks = split_into_chunks(rows, max_chunk_chars, overlap_seconds)
    if not chunks:
        raise ValueError("Could not divide transcript into chunks.")

    log.info("Transcript: %d segments, %d chunks", len(rows), len(chunks))

    candidates: list[dict] = []
    rejections = {reason: 0 for reason in REJECTION_REASONS}
    failed_chunks = 0
    last_error: Exception | None = None
    clips_per_chunk = max(1, min(3, math.ceil(clip_count / len(chunks)) + 1))

    for index, chunk in enumerate(chunks, start=1):
        if progress_callback:
            progress_callback(index, len(chunks))
        log.info(
            "Analyzing chunk %d/%d (%s - %s)",
            index, len(chunks), fmt_time(chunk["start_sec"]), fmt_time(chunk["end_sec"]),
        )

        data = None
        for attempt in range(2):
            try:
                data = client.chat_json(
                    build_system_prompt(retry=attempt == 1),
                    build_user_prompt(chunk["text"], clips_per_chunk, min_duration, max_duration),
                )
                break
            except ClipForgeError as exc:
                last_error = exc
                log.warning("Chunk %d attempt %d failed: %s", index, attempt + 1, exc)

        if data is None:
            failed_chunks += 1
            continue

        for raw_clip in data.get("clips", []):
            validated, reason = validate_clip(
                raw_clip, chunk, rows, video_duration, min_duration, max_duration, tolerance
            )
            if validated is None:
                rejections[reason or "invalid_structure"] += 1
            else:
                candidates.append(validated)

    if failed_chunks == len(chunks):
        raise AnalysisError(f"Every request to the local AI failed. Last error: {last_error}")

    if not candidates:
        raise AnalysisError(
            "No sufficiently supported clip candidates were found.\n\n"
            f"Chunks analyzed: {len(chunks)} (failed: {failed_chunks})\n"
            f"Rejected candidates: {rejections}\n\n"
            "Try another transcript or a stronger local model."
        )

    final = remove_duplicate_clips(candidates)
    final.sort(key=lambda clip: clip["quality_score"], reverse=True)
    final = final[: int(clip_count)]

    log.info(
        "Analysis summary: chunks=%d candidates=%d final=%d rejections=%s",
        len(chunks), len(candidates), len(final), rejections,
    )
    return AnalysisResult(final, len(chunks), failed_chunks, len(candidates), rejections)
