"""Page composition: wires the UI panels to the transcript, AI and rendering layers."""

from __future__ import annotations

import base64
import logging

import streamlit as st
import streamlit.components.v1 as components

from clipforge.ai.analyzer import analyze_transcript
from clipforge.ai.ollama import OllamaClient
from clipforge.config import get_settings
from clipforge.errors import ClipForgeError
from clipforge.logging_config import setup_logging
from clipforge.rendering.live_relay import (
    LiveRelayConfig,
    LiveVerticalRelay,
    StreamerBox,
    draw_box_on_png_bytes,
)
from clipforge.rendering.live_stream import (
    MAX_INTERVAL_MINUTES,
    MAX_SHOT_COUNT,
    MIN_INTERVAL_MINUTES,
    MIN_SHOT_COUNT,
    SHORT_LENGTH_OPTIONS,
    LiveShotConfig,
    generate_live_interval_shots,
)
from clipforge.transcript.youtube import fetch_transcript, get_video_id
from clipforge.ui import state
from clipforge.ui.clips_panel import render_clip_editor
from clipforge.ui.render_panel import render_section
from clipforge.ui.sidebar import SidebarSettings, render_sidebar
from clipforge.ui.transcript_panel import render_transcript
from clipforge.utils import fmt_time

log = logging.getLogger(__name__)

CORNER_PRESETS: dict[str, StreamerBox] = {
    "Custom (Sliders)": StreamerBox(0.05, 0.05, 0.35, 0.35),
    "Top-Left": StreamerBox(0.02, 0.02, 0.35, 0.35),
    "Top-Right": StreamerBox(0.63, 0.02, 0.35, 0.35),
    "Bottom-Left": StreamerBox(0.02, 0.63, 0.35, 0.35),
    "Bottom-Right": StreamerBox(0.63, 0.63, 0.35, 0.35),
}


def _render_hls_browser_preview(stream_url: str) -> None:
    """Render an hls.js video preview inside Streamlit for local/remote .m3u8 streams."""
    if not stream_url or not stream_url.lower().endswith(".m3u8"):
        return

    b64_url = base64.b64encode(stream_url.encode("utf-8")).decode("ascii")
    html = f"""
    <div style="background:#111;padding:10px;border-radius:8px;">
      <video id="cf-hls-video" controls autoplay muted playsinline
             style="width:100%;max-height:520px;background:#000;border-radius:6px;"></video>
      <div id="cf-hls-status" style="color:#ccc;font-size:12px;margin-top:6px;">
        Connecting to HLS stream...
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <script>
      (function() {{
        const url = atob("{b64_url}");
        const video = document.getElementById("cf-hls-video");
        const status = document.getElementById("cf-hls-status");
        if (!video) return;

        if (window.Hls && window.Hls.isSupported()) {{
          const hls = new window.Hls({{ lowLatencyMode: true, liveSyncDurationCount: 2 }});
          hls.loadSource(url);
          hls.attachMedia(video);
          hls.on(window.Hls.Events.MANIFEST_PARSED, function() {{
            video.play().catch(() => {{}});
            status.textContent = "Live HLS preview active (open in VLC or OBS for external playback).";
          }});
          hls.on(window.Hls.Events.ERROR, function(_, data) {{
            if (data && data.fatal) {{
              status.textContent = "Waiting for HLS segments or stream recovery...";
            }}
          }});
        }} else if (video.canPlayType("application/vnd.apple.mpegurl")) {{
          video.src = url;
          video.addEventListener("loadedmetadata", function() {{
            video.play().catch(() => {{}});
            status.textContent = "Live HLS preview active.";
          }});
        }} else {{
          status.textContent = "HLS playback unsupported in this browser view; open the link in VLC.";
        }}
      }})();
    </script>
    """
    components.html(html, height=580)


def _render_streamer_selector_on_live_frame(
    stream_url: str,
    ffmpeg_path: str,
    state_prefix: str = "streamer_selector",
) -> tuple[StreamerBox | None, bool]:
    """Grab full live frame and let user manually select or auto-detect the streamer box."""
    frame_key = f"{state_prefix}_full_frame"
    box_key = f"{state_prefix}_selected_box"
    relay_key = f"{state_prefix}_relay"

    if frame_key not in st.session_state:
        st.session_state[frame_key] = None
    if box_key not in st.session_state:
        st.session_state[box_key] = None
    if relay_key not in st.session_state:
        st.session_state[relay_key] = LiveVerticalRelay(ffmpeg_path=ffmpeg_path)

    relay: LiveVerticalRelay = st.session_state[relay_key]

    st.markdown("**Streamer Region Selection (Full Live Frame)**")
    act1, act2 = st.columns(2)

    if act1.button("Grab full live frame", key=f"{state_prefix}_grab_btn"):
        try:
            with st.spinner("Capturing full frame from live stream..."):
                png = relay.grab_full_frame_png(stream_url)
            if png:
                st.session_state[frame_key] = png
                if st.session_state[box_key] is None:
                    st.session_state[box_key] = StreamerBox(0.05, 0.05, 0.35, 0.35)
            else:
                st.warning("Could not grab a snapshot frame right now; try again.")
        except ClipForgeError as exc:
            st.error(str(exc))

    if act2.button("Auto-detect face (seed box)", key=f"{state_prefix}_autoseed_btn"):
        try:
            with st.spinner("Running auto-detection on live stream..."):
                box, found, preview_png = relay.detect_with_preview_from_source_url(stream_url)
            st.session_state[box_key] = box
            if preview_png and st.session_state[frame_key] is None:
                st.session_state[frame_key] = preview_png
            if found:
                st.success(
                    f"Auto-detected seed box: x={box.x:.2f}, y={box.y:.2f}, w={box.w:.2f}, h={box.h:.2f}"
                )
            else:
                st.info("No face auto-detected; adjust the box manually on the live frame below.")
        except ClipForgeError as exc:
            st.error(str(exc))

    selection_mode = st.radio(
        "Selection method",
        options=["Manual select from live frame", "Auto-detect face"],
        horizontal=True,
        key=f"{state_prefix}_mode",
    )
    is_manual = selection_mode == "Manual select from live frame"
    current_box: StreamerBox | None = st.session_state[box_key]

    if is_manual:
        preset_name = st.selectbox(
            "Quick position preset",
            options=list(CORNER_PRESETS.keys()),
            key=f"{state_prefix}_preset",
        )
        if preset_name != "Custom (Sliders)" and st.button(
            f"Apply {preset_name} preset", key=f"{state_prefix}_apply_preset"
        ):
            current_box = CORNER_PRESETS[preset_name]
            st.session_state[box_key] = current_box

        base = current_box or StreamerBox(0.05, 0.05, 0.35, 0.35)
        s1, s2, s3, s4 = st.columns(4)
        bx = s1.slider("Left (X)", 0.0, 0.90, float(base.x), 0.01, key=f"{state_prefix}_x")
        by = s2.slider("Top (Y)", 0.0, 0.90, float(base.y), 0.01, key=f"{state_prefix}_y")
        bw = s3.slider("Width (W)", 0.05, 1.00, float(base.w), 0.01, key=f"{state_prefix}_w")
        bh = s4.slider("Height (H)", 0.05, 1.00, float(base.h), 0.01, key=f"{state_prefix}_h")

        chosen_box = StreamerBox(x=bx, y=by, w=bw, h=bh)
        st.session_state[box_key] = chosen_box

        if st.session_state[frame_key] is not None:
            boxed_png = draw_box_on_png_bytes(
                st.session_state[frame_key],
                chosen_box,
                label="SELECTED STREAMER",
            )
            if boxed_png:
                st.image(
                    boxed_png,
                    caption=(
                        f"Full Live Frame — Selected Box: x={chosen_box.x:.2f}, y={chosen_box.y:.2f}, "
                        f"w={chosen_box.w:.2f}, h={chosen_box.h:.2f}"
                    ),
                    use_container_width=True,
                )
        return chosen_box, True

    if current_box is not None and st.session_state[frame_key] is not None:
        boxed_png = draw_box_on_png_bytes(
            st.session_state[frame_key],
            current_box,
            label="AUTO STREAMER",
        )
        if boxed_png:
            st.image(
                boxed_png,
                caption="Full Live Frame with Detected Box",
                use_container_width=True,
            )
    return current_box, False


def _extract_transcript(url: str, language: str) -> None:
    try:
        video_id = get_video_id(url)
        languages = list(dict.fromkeys([language, "en"]))
        with st.spinner("Extracting YouTube captions..."):
            rows = fetch_transcript(video_id, languages)
        state.set_transcript(video_id, rows)
        st.success(f"Successfully extracted {len(rows)} transcript segments.")
        st.info(f"Transcript duration: {fmt_time(max(r['end_sec'] for r in rows))}")
    except ClipForgeError as exc:
        st.error(f"Transcript extraction failed: {exc}")
        st.info(
            "Captions may be unavailable, disabled, or inaccessible. "
            "This version uses YouTube captions and does not automatically "
            "transcribe videos without captions."
        )


def _find_clips(rows: list[dict], side: SidebarSettings, settings) -> None:
    if not rows:
        st.warning("Extract a transcript first.")
        return
    if side.min_duration >= side.max_duration:
        st.warning("Maximum clip duration must be greater than minimum clip duration.")
        return

    client = OllamaClient(
        settings.ollama_url, side.model,
        timeout=settings.ollama_timeout, num_ctx=settings.ollama_num_ctx,
        max_tokens=settings.max_generation_tokens,
    )
    progress_bar = st.progress(0)
    progress_text = st.empty()

    def on_progress(done: int, total: int) -> None:
        progress_bar.progress(done / total)
        progress_text.caption(f"Analyzing transcript chunk {done} of {total}...")

    try:
        with st.spinner(f"{side.model} is analyzing the transcript. Please wait..."):
            result = analyze_transcript(
                rows, client, side.clip_count, side.min_duration, side.max_duration,
                max_chunk_chars=settings.max_chunk_chars,
                overlap_seconds=settings.chunk_overlap_seconds,
                tolerance=settings.timestamp_tolerance,
                progress_callback=on_progress,
            )
        state.set_clips(result.clips)
        progress_bar.progress(1.0)
        progress_text.success("Transcript analysis completed.")
        st.success(f"Found {len(result.clips)} supported clip candidates.")
        if result.chunks_failed:
            st.warning(
                f"{result.chunks_failed} of {result.chunks_total} transcript chunks "
                "could not be analyzed; results may be incomplete."
            )
    except (ClipForgeError, ValueError) as exc:
        state.set_clips([])
        progress_bar.empty()
        progress_text.empty()
        st.error(f"Local AI analysis failed: {exc}")


def _render_live_stream_shots_section(settings) -> None:
    """Capture live stream shorts (within 1m) every 1-10 minutes as vertical shots."""
    st.divider()
    st.subheader("📡 Live Stream Interval Shots")
    st.caption(
        "Paste an active YouTube live stream link, pick how often to capture (1 to 10 minutes), "
        "choose a short length within 1 minute (up to 60s), and set the total number of videos."
    )

    live_url = st.text_input(
        "Live YouTube stream URL",
        placeholder="https://www.youtube.com/live/...",
        key="live_stream_url_input",
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        interval_min = st.number_input(
            "Every how many minutes (1-10)",
            min_value=MIN_INTERVAL_MINUTES,
            max_value=MAX_INTERVAL_MINUTES,
            value=5,
            step=1,
            key="live_interval_minutes",
        )
    with c2:
        short_sec = st.selectbox(
            "Short video length (seconds, up to 60s)",
            options=list(SHORT_LENGTH_OPTIONS),
            index=len(SHORT_LENGTH_OPTIONS) - 1,
            key="live_short_seconds",
        )
    with c3:
        shot_count = st.number_input(
            "Total number of videos",
            min_value=MIN_SHOT_COUNT,
            max_value=MAX_SHOT_COUNT,
            value=3,
            step=1,
            key="live_shot_count",
        )

    _render_streamer_selector_on_live_frame(
        stream_url=live_url,
        ffmpeg_path=settings.ffmpeg_path,
        state_prefix="shots_streamer",
    )

    if "live_shots_archive" not in st.session_state:
        st.session_state.live_shots_archive = None
    if "live_shots_saved_path" not in st.session_state:
        st.session_state.live_shots_saved_path = None

    start_live = st.button(
        "Start live interval shot capture & render",
        type="primary",
        key="start_live_shots_btn",
    )

    if start_live:
        prog = st.progress(0, text="Preparing live stream capture…")
        status_msg = st.empty()

        def on_shot_progress(done: int, total: int, message: str) -> None:
            prog.progress((done - 1) / max(1, total), text=message)
            status_msg.caption(message)

        cfg = LiveShotConfig(
            stream_url=live_url,
            interval_minutes=int(interval_min),
            short_seconds=int(short_sec),
            shot_count=int(shot_count),
            auto_detect_facecam=True,
        )
        try:
            archive_bytes, saved_path = generate_live_interval_shots(
                cfg,
                ffmpeg_path=settings.ffmpeg_path,
                progress_callback=on_shot_progress,
            )
            st.session_state.live_shots_archive = archive_bytes
            st.session_state.live_shots_saved_path = str(saved_path)
            prog.progress(1.0, text="Completed.")
            st.success(
                f"Generated {int(shot_count)} live vertical shorts ({int(short_sec)}s each, "
                f"every {int(interval_min)} min) and auto-saved to `{saved_path}`."
            )
        except ClipForgeError as exc:
            st.session_state.live_shots_archive = None
            st.session_state.live_shots_saved_path = None
            prog.empty()
            st.error(f"Live stream shot generation failed: {exc}")

    if st.session_state.live_shots_saved_path:
        st.caption(f"Auto-saved archive: `{st.session_state.live_shots_saved_path}`")

    if st.session_state.live_shots_archive:
        st.download_button(
            "Download live interval shots (.zip)",
            data=st.session_state.live_shots_archive,
            file_name=f"clipforge_live_every{int(interval_min)}m_{int(short_sec)}s_shots.zip",
            mime="application/zip",
            key="download_live_shots_btn",
            on_click="ignore",
        )


def _render_live_vertical_relay_section(settings) -> None:
    """Continuously reformat an active live stream into 1080x1920 (streamer top / gameplay bottom)."""
    st.divider()
    st.subheader("📺 Live Vertical Stream Relay (1080×1920)")
    st.caption(
        "Paste a live YouTube stream URL to select or auto-detect the streamer box and continuously "
        "reformat the stream into vertical Shorts layout (streamer on top, gameplay on bottom)."
    )

    if "live_vertical_relay" not in st.session_state:
        st.session_state.live_vertical_relay = LiveVerticalRelay(ffmpeg_path=settings.ffmpeg_path)
    if "live_relay_link" not in st.session_state:
        st.session_state.live_relay_link = ""
    if "detected_streamer_box" not in st.session_state:
        st.session_state.detected_streamer_box = None

    relay: LiveVerticalRelay = st.session_state.live_vertical_relay

    source_url = st.text_input(
        "Source YouTube live stream URL",
        placeholder="https://www.youtube.com/watch?v=... or /live/...",
        key="relay_source_url",
    )

    c1, c2 = st.columns(2)
    with c1:
        dest_mode = st.selectbox(
            "Output destination",
            options=[
                "Sample local live link (HLS)",
                "Custom RTMP / RTMPS link (YouTube Live ready)",
            ],
            key="relay_dest_mode",
        )
    with c2:
        top_split = st.slider(
            "Top streamer height (%)",
            min_value=25,
            max_value=60,
            value=42,
            step=1,
            key="relay_top_split",
        )

    custom_target = ""
    if dest_mode.startswith("Custom RTMP"):
        custom_target = st.text_input(
            "Target RTMP / RTMPS stream URL",
            placeholder="rtmps://a.rtmp.youtube.com/live2/<your-stream-key>",
            key="relay_custom_target",
        )

    selected_box, is_manual = _render_streamer_selector_on_live_frame(
        stream_url=source_url,
        ffmpeg_path=settings.ffmpeg_path,
        state_prefix="relay_streamer",
    )

    b1, b2 = st.columns(2)
    start_clicked = b1.button("Start live vertical link", type="primary", key="start_relay_btn")
    stop_clicked = b2.button("Stop live vertical link", key="stop_relay_btn")

    if start_clicked:
        try:
            cfg = LiveRelayConfig(
                source_stream_url=source_url,
                top_ratio=top_split / 100.0,
                target_url=custom_target if dest_mode.startswith("Custom RTMP") else "",
                auto_detect_streamer=not is_manual,
                streamer_box=selected_box if is_manual else None,
            )
            link = relay.start(cfg)
            st.session_state.live_relay_link = link
            if relay.detected_box is not None:
                st.session_state.detected_streamer_box = relay.detected_box
            st.success("Live vertical stream relay is active.")
        except ClipForgeError as exc:
            st.error(str(exc))

    if stop_clicked:
        relay.stop()
        st.info("Live vertical stream relay stopped.")

    if relay.is_running and st.session_state.live_relay_link:
        st.markdown("**Active Live Vertical Stream Link:**")
        st.code(st.session_state.live_relay_link, language="text")
        _render_hls_browser_preview(st.session_state.live_relay_link)


def run() -> None:
    """Entry point called by the root ``app.py`` on every Streamlit rerun."""
    settings = get_settings()
    setup_logging(settings.log_level)

    st.set_page_config(page_title="ClipForge AI", page_icon="🎬", layout="wide")
    st.title("🎬 ClipForge AI")
    st.caption("Find interesting gaming moments and create short-form videos using local AI.")

    state.init_state()
    side = render_sidebar(settings)

    url = st.text_input("YouTube video URL", placeholder="https://www.youtube.com/watch?v=...")
    col1, col2 = st.columns(2)
    fetch = col1.button("1. Extract transcript", type="primary", width="stretch")
    analyze = col2.button("2. Find clip moments", width="stretch")

    if fetch:
        _extract_transcript(url, side.language)

    rows = st.session_state.transcript_rows
    render_transcript(rows)

    if analyze:
        _find_clips(rows, side, settings)

    clips = st.session_state.clips
    if clips:
        edited = render_clip_editor(clips, st.session_state.clips_version)
        render_section(edited, settings)
    else:
        st.info("Extract a transcript and find clip moments to see your suggested clips here.")

    _render_live_stream_shots_section(settings)
    _render_live_vertical_relay_section(settings)

    st.divider()
    st.caption(
        "ClipForge AI MVP · Powered by local Ollama, Qwen and FFmpeg. "
        "Transcript analysis cannot detect silent visual highlights. "
        "Video-frame and audio analysis can be added in a later version."
    )