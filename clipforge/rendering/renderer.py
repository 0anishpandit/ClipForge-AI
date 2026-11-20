"""Render approved clips from a local source video into vertical MP4s."""

from __future__ import annotations

import io
import logging
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from clipforge.errors import RenderError
from clipforge.rendering import layouts
from clipforge.rendering.facecam_detector import (
    DEFAULT_FACECAM_REGION,
    FrameSampler,
    detect_facecam_region,
)
from clipforge.rendering.ffmpeg import build_clip_command, find_ffmpeg, run_ffmpeg
from clipforge.rendering.regions import default_gameplay_region
from clipforge.utils import safe_float

log = logging.getLogger(__name__)

MIN_RENDER_SECONDS = 1
ProgressCallback = Callable[[int, int], None]


def validate_render_clips(rows: list[dict]) -> list[dict]:
    """Validate user-edited rows (e.g. from the table editor) before rendering."""
    valid = []
    for index, row in enumerate(rows, start=1):
        start = safe_float(row.get("start_sec"))
        end = safe_float(row.get("end_sec"))
        if start is None or end is None:
            raise RenderError(f"Clip {index} has invalid timestamps.")
        if start < 0 or end <= start:
            raise RenderError(f"Clip {index} has an invalid start/end time.")
        if end - start < MIN_RENDER_SECONDS:
            raise RenderError(f"Clip {index} is too short.")

        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            title = "highlight"  # also covers NaN/None from an edited table cell
        valid.append({"start_sec": start, "end_sec": end, "title": title})

    if not valid:
        raise RenderError("There are no valid clips to render.")
    return valid


def safe_filename(index: int, title: str) -> str:
    """``clip_01_Some_Title.mp4`` - safe on Windows, macOS and Linux."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")[:35]
    return f"clip_{index:02d}_{slug or 'highlight'}.mp4"


def resolve_layout_settings(
    source: Path,
    layout_settings: dict,
    *,
    sample_frames: int = 12,
    min_confidence: float = 0.25,
    sampler: FrameSampler | None = None,
) -> dict:
    """Resolve automatic facecam detection and defaults before building filter graphs."""
    resolved = dict(layout_settings)
    auto_detect = bool(resolved.get("auto_detect_facecam", False))
    layout = resolved.get("layout", layouts.FACECAM_GAMEPLAY)
    facecam = resolved.get("facecam_region")
    gameplay = resolved.get("gameplay_region")

    if auto_detect and layout in layouts.LAYOUTS_WITH_FACECAM:
        detection = detect_facecam_region(
            source,
            sample_frames=sample_frames,
            min_confidence=min_confidence,
            sampler=sampler,
        )
        facecam = detection.region
        resolved["facecam_region"] = facecam
        resolved["facecam_detected"] = detection.detected
        resolved["facecam_confidence"] = detection.confidence

    if layout == layouts.FACECAM_GAMEPLAY:
        if facecam is None:
            facecam = dict(DEFAULT_FACECAM_REGION)
            resolved["facecam_region"] = facecam
        if gameplay is None:
            gameplay = default_gameplay_region(facecam)
            resolved["gameplay_region"] = gameplay
    elif layout == layouts.FLOATING_FACECAM and facecam is None:
        facecam = dict(DEFAULT_FACECAM_REGION)
        resolved["facecam_region"] = facecam

    return resolved


def render_clips(
    source_path: Path | str,
    clips: list[dict],
    layout_settings: dict,
    *,
    ffmpeg_path: str = "",
    progress_callback: ProgressCallback | None = None,
    facecam_sample_frames: int = 12,
    facecam_min_confidence: float = 0.25,
    sampler: FrameSampler | None = None,
) -> bytes:
    """Render every clip and return a ZIP archive (bytes) of the MP4 files.

    ``layout_settings`` keys: ``layout``, ``facecam_region``, ``gameplay_region``,
    ``split_ratio``, ``auto_detect_facecam``.
    """
    source = Path(source_path)
    if not source.is_file():
        raise RenderError("Please provide a source video.")

    ffmpeg = find_ffmpeg(ffmpeg_path)
    clips = validate_render_clips(clips)
    effective_settings = resolve_layout_settings(
        source,
        layout_settings,
        sample_frames=facecam_sample_frames,
        min_confidence=facecam_min_confidence,
        sampler=sampler,
    )
    video_filter = layouts.build_video_filter(
        layout=effective_settings.get("layout", layouts.FACECAM_GAMEPLAY),
        facecam_region=effective_settings.get("facecam_region"),
        split_ratio=effective_settings.get("split_ratio", 30),
        gameplay_region=effective_settings.get("gameplay_region"),
    )

    with tempfile.TemporaryDirectory(prefix="clipforge_") as temp_dir:
        outputs: list[Path] = []
        for index, clip in enumerate(clips, start=1):
            if progress_callback:
                progress_callback(index, len(clips))
            output = Path(temp_dir) / safe_filename(index, clip["title"])
            command = build_clip_command(
                ffmpeg, source, output, clip["start_sec"],
                clip["end_sec"] - clip["start_sec"], video_filter,
            )
            log.info("Rendering clip %d/%d -> %s", index, len(clips), output.name)
            try:
                run_ffmpeg(command)
            except RenderError as exc:
                raise RenderError(f"Clip {index}: {exc}") from exc
            if not output.is_file() or output.stat().st_size == 0:
                raise RenderError(f"FFmpeg did not produce clip {index}.")
            outputs.append(output)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in outputs:
                archive.write(path, arcname=path.name)
        return buffer.getvalue()
