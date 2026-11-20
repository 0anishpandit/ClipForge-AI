"""Capture live-stream short clips (within 1 minute) every 1-10 minutes as vertical shots."""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from clipforge.config import PROJECT_ROOT
from clipforge.errors import LiveStreamError, RenderError
from clipforge.rendering import layouts
from clipforge.rendering.ffmpeg import find_ffmpeg
from clipforge.rendering.renderer import render_clips

log = logging.getLogger(__name__)

MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 10
MIN_SHOT_COUNT = 1
MAX_SHOT_COUNT = 48
MIN_SHORT_SECONDS = 10
MAX_SHORT_SECONDS = 60
SHORT_LENGTH_OPTIONS = (15, 30, 45, 60)
DEFAULT_LIVE_OUTPUT_DIR = PROJECT_ROOT / "outputs"

SegmentCaptureFn = Callable[[str, float, Path, str], None]
ShotProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class LiveShotConfig:
    """Configuration for capturing short clips (<=60s) at an interval of 1-10 minutes."""

    stream_url: str
    interval_minutes: int = 5
    short_seconds: int = 60
    shot_count: int = 3
    split_ratio: int = 42
    auto_detect_facecam: bool = True
    facecam_sample_frames: int = 24
    facecam_min_confidence: float = 0.15
    output_dir: Path = DEFAULT_LIVE_OUTPUT_DIR


def validate_live_shot_config(cfg: LiveShotConfig) -> LiveShotConfig:
    """Validate URL, interval minutes (1-10), short clip length (<=60s), and shot count."""
    url = (cfg.stream_url or "").strip()
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise LiveStreamError(
            "Please enter a valid live stream URL starting with http:// or https://."
        )

    if not isinstance(cfg.interval_minutes, int) or isinstance(cfg.interval_minutes, bool):
        raise LiveStreamError("Interval time must be a whole number of minutes.")
    if not MIN_INTERVAL_MINUTES <= cfg.interval_minutes <= MAX_INTERVAL_MINUTES:
        raise LiveStreamError(
            f"Interval time must be between {MIN_INTERVAL_MINUTES} and {MAX_INTERVAL_MINUTES} minutes."
        )

    if not isinstance(cfg.short_seconds, int) or isinstance(cfg.short_seconds, bool):
        raise LiveStreamError("Short clip duration must be a whole number of seconds.")
    if not MIN_SHORT_SECONDS <= cfg.short_seconds <= MAX_SHORT_SECONDS:
        raise LiveStreamError(
            f"Short clip duration must be between {MIN_SHORT_SECONDS} and {MAX_SHORT_SECONDS} seconds (within 1 minute)."
        )

    if not isinstance(cfg.shot_count, int) or isinstance(cfg.shot_count, bool):
        raise LiveStreamError("Total number of shots must be a whole number.")
    if not MIN_SHOT_COUNT <= cfg.shot_count <= MAX_SHOT_COUNT:
        raise LiveStreamError(
            f"Total number of shots must be between {MIN_SHOT_COUNT} and {MAX_SHOT_COUNT}."
        )

    out_dir = Path(cfg.output_dir) if cfg.output_dir else DEFAULT_LIVE_OUTPUT_DIR
    return LiveShotConfig(
        stream_url=url,
        interval_minutes=cfg.interval_minutes,
        short_seconds=cfg.short_seconds,
        shot_count=cfg.shot_count,
        split_ratio=cfg.split_ratio,
        auto_detect_facecam=cfg.auto_detect_facecam,
        facecam_sample_frames=cfg.facecam_sample_frames,
        facecam_min_confidence=cfg.facecam_min_confidence,
        output_dir=out_dir,
    )


def _yt_dlp_prefix() -> list[str]:
    """Return the command prefix needed to run ``yt-dlp`` from the active env or PATH."""
    found = shutil.which("yt-dlp")
    if found:
        return [found]

    scripts_exe = Path(sys.executable).resolve().parent / (
        "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
    )
    if scripts_exe.is_file():
        return [str(scripts_exe)]

    probe = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "yt_dlp"]

    raise LiveStreamError(
        "yt-dlp was not found in the active Python environment or PATH. "
        "Install it with 'python -m pip install -U yt-dlp' and restart Streamlit."
    )


def find_yt_dlp() -> str:
    """Locate ``yt-dlp`` on PATH, active venv Scripts, or as a Python module."""
    prefix = _yt_dlp_prefix()
    return " ".join(prefix)


def capture_live_segment_ytdlp(
    stream_url: str,
    duration_seconds: float,
    output_path: Path,
    ffmpeg_path: str = "",
) -> None:
    """Record ``duration_seconds`` from a live stream URL into ``output_path`` via yt-dlp + FFmpeg."""
    yt_dlp_cmd = _yt_dlp_prefix()
    ffmpeg = find_ffmpeg(ffmpeg_path)

    format_selectors = [
        "bv*+ba/b",
        "best/bv*+ba",
    ]
    media_urls: list[str] = []
    last_stderr = ""

    for fmt in format_selectors:
        resolve_cmd = [
            *yt_dlp_cmd,
            "--no-warnings",
            "--no-playlist",
            "-f",
            fmt,
            "-g",
            stream_url,
        ]
        resolved = subprocess.run(
            resolve_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if resolved.returncode == 0:
            candidate_urls = [line.strip() for line in resolved.stdout.splitlines() if line.strip()]
            if candidate_urls:
                media_urls = candidate_urls
                break
        last_stderr = resolved.stderr[-1500:]

    if not media_urls:
        raise LiveStreamError(
            f"Could not read live stream URL with yt-dlp:\n{last_stderr}"
        )

    record_cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-y",
    ]
    for m_url in media_urls[:2]:
        record_cmd.extend([
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            m_url,
        ])

    record_cmd.extend([
        "-t",
        str(duration_seconds),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        str(output_path),
    ])
    try:
        recorded = subprocess.run(
            record_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(duration_seconds) + 60,
        )
    except subprocess.TimeoutExpired as exc:
        raise LiveStreamError(
            f"Timed out while recording {duration_seconds:.0f}s live short."
        ) from exc

    if recorded.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        raise LiveStreamError(
            f"Failed to record {duration_seconds:.0f}s live short:\n{recorded.stderr[-1500:]}"
        )


def save_live_shots_archive(
    archive_bytes: bytes,
    interval_minutes: int,
    short_seconds: int,
    shot_count: int,
    output_dir: Path = DEFAULT_LIVE_OUTPUT_DIR,
) -> Path:
    """Persist a rendered live-shorts ZIP archive to disk and return its path."""
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = (
        f"clipforge_live_every{interval_minutes}m_{short_seconds}s_"
        f"{shot_count}shots_{stamp}.zip"
    )
    saved_path = target_dir / filename
    saved_path.write_bytes(archive_bytes)
    log.info("Auto-saved live shorts archive to %s", saved_path)
    return saved_path


def generate_live_interval_shots(
    config: LiveShotConfig,
    *,
    ffmpeg_path: str = "",
    capture_fn: SegmentCaptureFn | None = None,
    progress_callback: ShotProgressCallback | None = None,
    segment_seconds_override: float | None = None,
) -> tuple[bytes, Path]:
    """Capture a ``<=60s`` short every ``interval_minutes`` (1-10m), render vertical shots, and save ZIP."""
    valid_cfg = validate_live_shot_config(config)
    ffmpeg = find_ffmpeg(ffmpeg_path)
    capturer = capture_fn or capture_live_segment_ytdlp
    clip_seconds = (
        float(segment_seconds_override)
        if segment_seconds_override is not None
        else float(valid_cfg.short_seconds)
    )
    interval_seconds = float(valid_cfg.interval_minutes * 60)
    wait_between_shots = max(0.0, interval_seconds - clip_seconds)

    layout_settings = {
        "layout": layouts.FACECAM_GAMEPLAY,
        "split_ratio": valid_cfg.split_ratio,
        "auto_detect_facecam": valid_cfg.auto_detect_facecam,
        "gameplay_region": {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0},
    }

    with tempfile.TemporaryDirectory(prefix="clipforge_live_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        rendered_shots: list[tuple[str, bytes]] = []

        for shot_idx in range(1, valid_cfg.shot_count + 1):
            if shot_idx > 1 and wait_between_shots > 0 and capture_fn is None:
                if progress_callback:
                    progress_callback(
                        shot_idx,
                        valid_cfg.shot_count,
                        f"Waiting {int(wait_between_shots)}s until next {valid_cfg.interval_minutes}m interval for shot {shot_idx}/{valid_cfg.shot_count}…",
                    )
                time.sleep(wait_between_shots)

            raw_seg = tmp_path / f"raw_shot_{shot_idx:02d}.mp4"
            if progress_callback:
                progress_callback(
                    shot_idx,
                    valid_cfg.shot_count,
                    f"Capturing {int(clip_seconds)}s short for shot {shot_idx}/{valid_cfg.shot_count}…",
                )
            try:
                capturer(valid_cfg.stream_url, clip_seconds, raw_seg, ffmpeg)
            except LiveStreamError:
                raise
            except Exception as exc:
                raise LiveStreamError(f"Shot {shot_idx} capture failed: {exc}") from exc

            if not raw_seg.is_file() or raw_seg.stat().st_size == 0:
                raise LiveStreamError(f"Shot {shot_idx} produced an empty live segment.")

            if progress_callback:
                progress_callback(
                    shot_idx,
                    valid_cfg.shot_count,
                    f"Rendering vertical shot {shot_idx}/{valid_cfg.shot_count} ({int(clip_seconds)}s)…",
                )

            clip_spec = [{
                "start_sec": 0.0,
                "end_sec": max(1.0, clip_seconds),
                "title": f"live_every_{valid_cfg.interval_minutes}m_{int(clip_seconds)}s_shot_{shot_idx:02d}",
            }]
            try:
                single_zip = render_clips(
                    raw_seg,
                    clip_spec,
                    layout_settings,
                    ffmpeg_path=ffmpeg,
                    facecam_sample_frames=valid_cfg.facecam_sample_frames,
                    facecam_min_confidence=valid_cfg.facecam_min_confidence,
                )
            except RenderError as exc:
                raise LiveStreamError(f"Shot {shot_idx} vertical render failed: {exc}") from exc

            with zipfile.ZipFile(io.BytesIO(single_zip), "r") as szf:
                names = szf.namelist()
                if not names:
                    raise LiveStreamError(f"Shot {shot_idx} render archive was empty.")
                mp4_bytes = szf.read(names[0])

            shot_filename = f"shot_{shot_idx:02d}_{int(clip_seconds)}s.mp4"
            rendered_shots.append((shot_filename, mp4_bytes))
            log.info("Completed live short %d/%d -> %s", shot_idx, valid_cfg.shot_count, shot_filename)

        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, data in rendered_shots:
                zf.writestr(fname, data)
        archive_bytes = out_buf.getvalue()

    saved_path = save_live_shots_archive(
        archive_bytes,
        interval_minutes=valid_cfg.interval_minutes,
        short_seconds=int(clip_seconds),
        shot_count=valid_cfg.shot_count,
        output_dir=valid_cfg.output_dir,
    )
    return archive_bytes, saved_path