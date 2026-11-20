"""Layout controls, source-video upload and the render button."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import streamlit as st

from clipforge.config import Settings
from clipforge.errors import ClipForgeError
from clipforge.rendering import layouts
from clipforge.rendering.facecam_detector import DEFAULT_FACECAM_REGION
from clipforge.rendering.regions import default_gameplay_region
from clipforge.rendering.renderer import render_clips


def _region_sliders(prefix: str, label: str, defaults: tuple[int, int, int, int]) -> dict | None:
    dx, dy, dw, dh = defaults
    left, right = st.columns(2)
    with left:
        x = st.slider(f"{label} left position (%)", 0, 95, dx, key=f"{prefix}_x")
        y = st.slider(f"{label} top position (%)", 0, 95, dy, key=f"{prefix}_y")
    with right:
        width = st.slider(f"{label} width (%)", 5, 100, dw, key=f"{prefix}_width")
        height = st.slider(f"{label} height (%)", 5, 100, dh, key=f"{prefix}_height")

    if x + width <= 100 and y + height <= 100:
        return {"x": x, "y": y, "width": width, "height": height}
    st.error(f"The {label.lower()} selection extends outside the video boundary.")
    return None


def _layout_settings() -> tuple[dict, bool]:
    st.subheader("📐 Vertical Layout Settings")
    mode = st.radio(
        "How do you want to configure the layout?",
        ["Automatic (facecam top + gameplay bottom)", "Manual"],
        horizontal=True, key="layout_mode",
    )

    auto_detect_facecam = False
    if mode != "Manual":
        st.info(
            "Automatic mode detects the streamer's facecam across the stream, "
            "enlarges the cropped streamer view on top, and places gameplay below in 1080×1920."
        )
        layout = layouts.FACECAM_GAMEPLAY
        auto_detect_facecam = True
        facecam = dict(DEFAULT_FACECAM_REGION)
        gameplay = default_gameplay_region(facecam)
        split_ratio = st.slider(
            "Streamer section height (%)",
            layouts.MIN_SPLIT_PERCENT,
            layouts.MAX_SPLIT_PERCENT,
            layouts.DEFAULT_FACECAM_SPLIT_PERCENT,
            key="auto_split_ratio",
        )
        st.caption(f"Preview proportions: streamer {split_ratio}% / gameplay {100 - split_ratio}%.")
    else:
        layout = st.selectbox("Choose your layout", list(layouts.ALL_LAYOUTS), key="selected_layout")
        auto_detect_facecam = st.checkbox(
            "Auto-detect streamer facecam region",
            value=False,
            key="manual_auto_detect_facecam",
        )
        facecam = gameplay = None
        split_ratio = layouts.DEFAULT_FACECAM_SPLIT_PERCENT

        if layout in layouts.LAYOUTS_WITH_FACECAM:
            st.markdown("### 1. Select streamer / facecam region")
            st.caption(
                "These coordinates are percentages of the original video frame. "
                "Adjust them to tightly cover the streamer's webcam."
            )
            facecam = _region_sliders("facecam", "Facecam", (2, 42, 19, 17))

        if layout == layouts.FACECAM_GAMEPLAY:
            st.markdown("### 2. Select gameplay region")
            st.caption(
                "Select the gameplay area separately. Exclude the webcam overlay "
                "where possible. This crop becomes the lower section."
            )
            gameplay = _region_sliders("gameplay", "Gameplay", (0, 0, 100, 100))
            split_ratio = st.slider(
                "Streamer section height (%)",
                layouts.MIN_SPLIT_PERCENT,
                layouts.MAX_SPLIT_PERCENT,
                layouts.DEFAULT_FACECAM_SPLIT_PERCENT,
                key="split_ratio",
            )
            st.caption(f"Preview proportions: streamer {split_ratio}% / gameplay {100 - split_ratio}%.")

    invalid = False
    if layout in layouts.LAYOUTS_WITH_FACECAM:
        invalid = facecam is None
    if layout == layouts.FACECAM_GAMEPLAY:
        invalid = invalid or gameplay is None

    layout_cfg = {
        "layout": layout,
        "facecam_region": facecam,
        "gameplay_region": gameplay,
        "split_ratio": split_ratio,
        "auto_detect_facecam": auto_detect_facecam,
    }
    return layout_cfg, not invalid


def _render_to_archive(
    video_file, clips: list[dict], layout_settings: dict, settings: Settings
) -> bytes:
    suffix = Path(video_file.name).suffix or ".mp4"
    progress = st.progress(0, text="Preparing…")

    def on_progress(done: int, total: int) -> None:
        progress.progress((done - 1) / total, text=f"Rendering clip {done} of {total}…")

    try:
        with tempfile.TemporaryDirectory(prefix="clipforge_src_") as tmp:
            source = Path(tmp) / f"source_video{suffix}"
            video_file.seek(0)
            with open(source, "wb") as handle:
                shutil.copyfileobj(video_file, handle, length=8 * 1024 * 1024)
            archive = render_clips(
                source,
                clips,
                layout_settings,
                ffmpeg_path=settings.ffmpeg_path,
                progress_callback=on_progress,
                facecam_sample_frames=settings.facecam_sample_frames,
                facecam_min_confidence=settings.facecam_min_confidence,
            )
        progress.progress(1.0, text="Done.")
        return archive
    except Exception:
        progress.empty()
        raise


def render_section(clips: list[dict], settings: Settings) -> None:
    st.divider()
    st.subheader("🎬 Render clips")
    st.write(
        "Upload the original video file to render your selected moments as vertical MP4 clips."
    )
    st.caption(
        "Only upload videos you own or are authorized to edit. "
        "YouTube transcript extraction does not download videos."
    )

    video_file = st.file_uploader(
        "Choose source video", type=["mp4", "mov", "mkv", "webm"], key="source_video_uploader"
    )
    layout_settings, layout_ok = _layout_settings()

    st.divider()
    clicked = st.button(
        "Render approved clips as vertical MP4s",
        type="primary",
        disabled=(video_file is None or not layout_ok),
        width="stretch",
    )

    if clicked:
        try:
            st.session_state.render_archive = _render_to_archive(
                video_file, clips, layout_settings, settings
            )
            st.success("Your clips have been rendered successfully.")
        except (ClipForgeError, ValueError) as exc:
            st.session_state.render_archive = None
            st.error(f"Rendering failed: {exc}")

    if st.session_state.render_archive:
        st.download_button(
            "Download all rendered clips (.zip)",
            data=st.session_state.render_archive,
            file_name="clipforge_exports.zip",
            mime="application/zip",
            on_click="ignore",
        )