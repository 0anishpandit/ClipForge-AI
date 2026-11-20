"""YouTube URL parsing and caption retrieval."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from clipforge.errors import TranscriptError
from clipforge.utils import fmt_time

_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
}
_PATH_PREFIXES = {"shorts", "live", "embed"}
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


def get_video_id(url: str) -> str:
    """Extract the 11-character video ID from a supported YouTube URL.

    Raises ``TranscriptError`` for anything that is not a recognised URL.
    """
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    video_id = None

    if host in _SHORT_HOSTS:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        else:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in _PATH_PREFIXES:
                video_id = parts[1]

    if not video_id or not _VIDEO_ID_RE.fullmatch(video_id):
        raise TranscriptError("Invalid YouTube video URL.")
    return video_id


def fetch_transcript(video_id: str, languages: list[str]) -> list[dict]:
    """Fetch captions and return rows sorted by start time.

    Each row: ``{"start_sec", "end_sec", "timestamp", "text"}``.
    """
    # Imported lazily so the rest of the package (and its tests) work without
    # the network-facing dependency being importable.
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=languages)
    except Exception as exc:  # the library raises many specific types
        raise TranscriptError(str(exc) or exc.__class__.__name__) from exc

    rows = []
    for item in fetched:
        start = float(item.start)
        duration = float(item.duration)
        text = str(item.text).replace("\n", " ").strip()
        if not text:
            continue
        rows.append({
            "start_sec": round(start, 2),
            "end_sec": round(start + duration, 2),
            "timestamp": fmt_time(start),
            "text": text,
        })

    rows.sort(key=lambda row: row["start_sec"])
    if not rows:
        raise TranscriptError("No transcript segments were found.")
    return rows
