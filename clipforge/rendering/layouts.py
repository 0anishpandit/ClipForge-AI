"""Vertical (1080x1920) layouts, expressed as FFmpeg ``-filter_complex`` graphs."""

from __future__ import annotations

from clipforge.errors import RenderError
from clipforge.rendering.regions import default_gameplay_region, region_crop_filter

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

BLURRED = "Blurred background"
FULLSCREEN = "Full-screen crop"
FACECAM_GAMEPLAY = "Facecam + gameplay"
FLOATING_FACECAM = "Floating facecam"

ALL_LAYOUTS = (FACECAM_GAMEPLAY, FLOATING_FACECAM, BLURRED, FULLSCREEN)
LAYOUTS_WITH_FACECAM = (FACECAM_GAMEPLAY, FLOATING_FACECAM)

MIN_SPLIT_PERCENT = 20
MAX_SPLIT_PERCENT = 55
DEFAULT_FACECAM_SPLIT_PERCENT = 42
FLOATING_FACECAM_WIDTH = 360
FLOATING_FACECAM_MARGIN = 35


def _even(value: int) -> int:
    even_val = value - (value % 2)
    return max(2, even_val)


def build_video_filter(
    layout: str,
    facecam_region: dict | None = None,
    split_ratio: int = DEFAULT_FACECAM_SPLIT_PERCENT,
    gameplay_region: dict | None = None,
) -> str:
    w, h = OUTPUT_WIDTH, OUTPUT_HEIGHT

    if layout == BLURRED:
        return (
            "[0:v]split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,"
            f"crop={w}:{h},boxblur=20:10[bgv];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd,"
            "unsharp=3:3:0.4:3:3:0.0[fgv];"
            "[bgv][fgv]overlay=(W-w)/2:(H-h)/2:format=auto,setsar=1[v]"
        )

    if layout == FULLSCREEN:
        return (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,"
            f"crop={w}:{h},unsharp=3:3:0.4:3:3:0.0,setsar=1[v]"
        )

    if layout == FACECAM_GAMEPLAY:
        face_crop = region_crop_filter(facecam_region, "facecam")
        effective_gameplay = (
            gameplay_region
            if gameplay_region is not None
            else default_gameplay_region(facecam_region)
        )
        game_crop = region_crop_filter(effective_gameplay, "gameplay")

        try:
            split = int(split_ratio)
        except (TypeError, ValueError) as exc:
            raise RenderError("Facecam section height must be a number.") from exc
        if not MIN_SPLIT_PERCENT <= split <= MAX_SPLIT_PERCENT:
            raise RenderError(
                f"Facecam section height must be between {MIN_SPLIT_PERCENT}% "
                f"and {MAX_SPLIT_PERCENT}%."
            )

        face_h = _even(int(round(h * split / 100)))
        game_h = h - face_h
        return (
            "[0:v]split=2[face_src][game_src];"
            f"[face_src]{face_crop},"
            f"scale={w}:{face_h}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,"
            f"crop={w}:{face_h},unsharp=3:3:0.55:3:3:0.0[face];"
            f"[game_src]{game_crop},"
            f"scale={w}:{game_h}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,"
            f"crop={w}:{game_h},unsharp=3:3:0.35:3:3:0.0[game];"
            "[face][game]vstack=inputs=2,setsar=1[v]"
        )

    if layout == FLOATING_FACECAM:
        face_crop = region_crop_filter(facecam_region, "facecam")
        m = FLOATING_FACECAM_MARGIN
        return (
            "[0:v]split=2[bg_src][face_src];"
            f"[bg_src]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,"
            f"crop={w}:{h}[bg];"
            f"[face_src]{face_crop},scale={FLOATING_FACECAM_WIDTH}:-2:flags=lanczos+accurate_rnd,"
            f"unsharp=3:3:0.5:3:3:0.0[face];"
            f"[bg][face]overlay=W-w-{m}:{m}:format=auto,setsar=1[v]"
        )

    raise RenderError(f"Unsupported video layout: {layout}")