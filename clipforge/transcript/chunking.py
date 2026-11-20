"""Split a long transcript into overlapping, size-limited chunks for the AI."""

from __future__ import annotations

from clipforge.config import DEFAULT_CHUNK_OVERLAP_SECONDS, DEFAULT_MAX_CHUNK_CHARS
from clipforge.transcript.formatting import format_row_for_ai


def split_into_chunks(
    rows: list[dict],
    max_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    overlap_seconds: float = DEFAULT_CHUNK_OVERLAP_SECONDS,
) -> list[dict]:
    """Group rows into chunks of at most ``max_chars`` characters.

    Consecutive chunks overlap by roughly ``overlap_seconds`` so a moment that
    straddles a boundary is seen whole by at least one chunk.

    Each chunk: ``{"text", "start_sec", "end_sec", "rows"}``.
    """
    chunks: list[dict] = []
    total = len(rows)
    start_index = 0

    while start_index < total:
        current: list[dict] = []
        chars = 0
        index = start_index

        while index < total:
            extra = len(format_row_for_ai(rows[index])) + 1
            if current and chars + extra > max_chars:
                break
            current.append(rows[index])
            chars += extra
            index += 1

        if not current:
            break

        chunks.append({
            "text": "\n".join(format_row_for_ai(r) for r in current),
            "start_sec": float(current[0]["start_sec"]),
            "end_sec": float(current[-1]["end_sec"]),
            "rows": current,
        })

        if index >= total:
            break

        # Step back so the next chunk starts ~overlap_seconds before this one ended.
        previous_end = float(current[-1]["end_sec"])
        next_start = index
        while next_start > start_index:
            if float(rows[next_start - 1]["start_sec"]) < previous_end - overlap_seconds:
                break
            next_start -= 1
        if next_start <= start_index:  # guarantee forward progress
            next_start = index
        start_index = next_start

    return chunks
