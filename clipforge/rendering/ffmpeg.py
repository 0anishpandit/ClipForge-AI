"""Thin wrapper around the FFmpeg executable."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from clipforge.errors import RenderError

ENCODE_ARGS = [
    "-c:v", "libx264",
    "-preset", "slow",
    "-crf", "14",
    "-tune", "film",
    "-pix_fmt", "yuv420p",
    "-profile:v", "high",
    "-level:v", "4.2",
    "-bf", "3",
    "-g", "60",
    "-c:a", "aac",
    "-b:a", "320k",
    "-ar", "48000",
    "-movflags", "+faststart",
]


def find_ffmpeg(configured_path: str = "") -> str:
    """Locate FFmpeg: an explicit path first, otherwise ``PATH``."""
    candidate = configured_path.strip() if configured_path else ""
    if candidate:
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
        raise RenderError(f"Configured FFmpeg was not found: {candidate}")

    found = shutil.which("ffmpeg")
    if not found:
        raise RenderError(
            "FFmpeg was not found. Install it and add it to PATH "
            "(or set CLIPFORGE_FFMPEG). See README.md."
        )
    return found


def build_clip_command(
    ffmpeg: str, source: Path, output: Path, start: float, duration: float, video_filter: str
) -> list[str]:
    """Command that cuts ``[start, start+duration]`` and applies the filter graph."""
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "warning", "-y",
        "-ss", str(start), "-i", str(source), "-t", str(duration),
        "-filter_complex", video_filter,
        "-map", "[v]", "-map", "0:a?",
        *ENCODE_ARGS,
        str(output),
    ]


def run_ffmpeg(command: list[str]) -> None:
    """Run FFmpeg; raise ``RenderError`` with the tail of stderr on failure."""
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RenderError(f"FFmpeg failed:\n{result.stderr[-2500:]}")
    if "Output file is empty" in result.stderr:
        raise RenderError(
            "FFmpeg produced no video. The clip's start time is probably "
            "beyond the end of the source video."
        )