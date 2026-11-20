"""Continuous vertical (1080x1920) live-stream reframe and relay engine."""

from __future__ import annotations

import functools
import http.server
import logging
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from clipforge.config import PROJECT_ROOT
from clipforge.errors import LiveStreamError
from clipforge.rendering.ffmpeg import find_ffmpeg

log = logging.getLogger(__name__)

DEFAULT_RELAY_ROOT = PROJECT_ROOT / "outputs" / "live_relay"
DEFAULT_SAMPLE_HOST = "127.0.0.1"
DEFAULT_SAMPLE_PORT = 8765


@dataclass(frozen=True)
class StreamerBox:
    """Normalized (0.0 - 1.0) bounding box for the streamer's webcam region."""

    x: float
    y: float
    w: float
    h: float


@dataclass
class LiveRelayConfig:
    """Configuration for live vertical (1080x1920) stream reformatting and relay."""

    source_stream_url: str
    top_ratio: float = 0.42
    target_url: str = ""
    sample_port: int = DEFAULT_SAMPLE_PORT
    relay_dir: Path = field(default_factory=lambda: DEFAULT_RELAY_ROOT)
    auto_detect_streamer: bool = True
    streamer_box: StreamerBox | None = None


class _QuietHLSHandler(http.server.SimpleHTTPRequestHandler):
    """Serve generated live HLS segments with permissive CORS/cache headers."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        log.debug("Relay HTTP: " + format, *args)


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _find_faces_in_gray(
    gray,
    cascade,
    scale_factor: float,
    min_neighbors: int,
    min_face: int,
):
    return cascade.detectMultiScale(
        gray,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=(min_face, min_face),
    )


def _detect_box_single_frame(frame_bgr, cascade) -> StreamerBox | None:
    """Detect streamer face across standard and low-light contrast passes, then expand to webcam box."""
    import cv2

    if frame_bgr is None or frame_bgr.size == 0:
        return None

    img_h, img_w = frame_bgr.shape[:2]
    min_face = max(24, min(img_w, img_h) // 30)

    base_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced_gray = clahe.apply(base_gray)

    passes = [
        (base_gray, 1.1, 5),
        (enhanced_gray, 1.1, 4),
        (enhanced_gray, 1.15, 3),
    ]

    faces = ()
    for gray_img, sf, mn in passes:
        found = _find_faces_in_gray(gray_img, cascade, sf, mn, min_face)
        if len(found) > 0:
            faces = found
            break

    if len(faces) == 0:
        return None

    def score_face(box) -> float:
        _, _, fw, fh = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        area_ratio = (fw * fh) / float(img_w * img_h)
        if area_ratio > 0.35:
            return area_ratio * 0.25
        return area_ratio

    fx, fy, fw, fh = max(faces, key=score_face)
    fx, fy, fw, fh = int(fx), int(fy), int(fw), int(fh)

    cam_w = min(img_w, max(fw, int(round(fw * 2.4))))
    cam_h = min(img_h, max(fh, int(round(fh * 2.6))))
    center_x = fx + fw // 2
    center_y = fy + int(round(fh * 0.65))

    x1 = max(0, min(img_w - cam_w, center_x - cam_w // 2))
    y1 = max(0, min(img_h - cam_h, center_y - cam_h // 2))

    return StreamerBox(
        x=round(x1 / img_w, 4),
        y=round(y1 / img_h, 4),
        w=round(cam_w / img_w, 4),
        h=round(cam_h / img_h, 4),
    )


def detect_streamer_box_multi_pass(
    snapshot_paths: list[Path],
    fallback: StreamerBox = StreamerBox(0.0, 0.0, 0.40, 0.35),
) -> tuple[StreamerBox, bool]:
    """Multi-pass face detection across sampled frames to locate streamer webcam box."""
    try:
        import cv2
    except ImportError:
        log.warning("OpenCV (cv2) not installed; using fallback streamer box.")
        return fallback, False

    cascade_cls = getattr(cv2, "CascadeClassifier", None)
    cv2_data = getattr(cv2, "data", None)
    if cascade_cls is None or cv2_data is None:
        log.warning("OpenCV build lacks CascadeClassifier/data; using fallback streamer box.")
        return fallback, False

    cascade_path = str(Path(cv2_data.haarcascades) / "haarcascade_frontalface_default.xml")
    cascade = cascade_cls(cascade_path)
    if cascade.empty():
        return fallback, False

    candidates: list[StreamerBox] = []
    for path in snapshot_paths:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        frame = cv2.imread(str(path))
        box = _detect_box_single_frame(frame, cascade)
        if box is not None:
            candidates.append(box)

    if not candidates:
        return fallback, False

    n = len(candidates)
    med_x = sorted(c.x for c in candidates)[n // 2]
    med_y = sorted(c.y for c in candidates)[n // 2]
    med_w = sorted(c.w for c in candidates)[n // 2]
    med_h = sorted(c.h for c in candidates)[n // 2]

    return StreamerBox(x=med_x, y=med_y, w=med_w, h=med_h), True


def draw_box_on_png_bytes(
    image_bytes: bytes | None,
    box: StreamerBox,
    label: str = "STREAMER BOX",
) -> bytes | None:
    """Draw a normalized StreamerBox onto PNG/JPG frame bytes and return updated PNG bytes."""
    if not image_bytes:
        return None
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return image_bytes

        img_h, img_w = frame.shape[:2]
        x1 = max(0, min(img_w - 1, int(round(box.x * img_w))))
        y1 = max(0, min(img_h - 1, int(round(box.y * img_h))))
        x2 = max(x1 + 1, min(img_w, int(round((box.x + box.w) * img_w))))
        y2 = max(y1 + 1, min(img_h, int(round((box.y + box.h) * img_h))))

        color = (0, 230, 118)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        cv2.putText(
            frame,
            label,
            (x1, max(26, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv2.LINE_AA,
        )
        ok, enc = cv2.imencode(".png", frame)
        return enc.tobytes() if ok else image_bytes
    except Exception:
        return image_bytes


def render_detection_preview_bytes(
    image_path: Path,
    box: StreamerBox,
    detected: bool,
) -> bytes | None:
    """Draw the detected streamer box on a snapshot frame and return PNG bytes for UI preview."""
    try:
        import cv2
    except ImportError:
        return None

    if not image_path.is_file() or image_path.stat().st_size == 0:
        return None

    frame = cv2.imread(str(image_path))
    if frame is None or frame.size == 0:
        return None

    img_h, img_w = frame.shape[:2]
    x1 = max(0, min(img_w - 1, int(round(box.x * img_w))))
    y1 = max(0, min(img_h - 1, int(round(box.y * img_h))))
    x2 = max(x1 + 1, min(img_w, int(round((box.x + box.w) * img_w))))
    y2 = max(y1 + 1, min(img_h, int(round((box.y + box.h) * img_h))))

    color = (0, 220, 0) if detected else (0, 165, 255)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)

    label = "STREAMER (AUTO)" if detected else "FALLBACK BOX (VERIFY)"
    label_y = max(24, y1 - 10)
    cv2.putText(
        frame,
        label,
        (x1, label_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        color,
        2,
        cv2.LINE_AA,
    )

    ok, encoded = cv2.imencode(".png", frame)
    return encoded.tobytes() if ok else None


class LiveVerticalRelay:
    """Runs yt-dlp + FFmpeg continuously while a source live stream produces data."""

    def __init__(self, ffmpeg_path: str = "") -> None:
        self.ffmpeg_path = ffmpeg_path
        self._proc: subprocess.Popen[str] | None = None
        self._httpd: _ReusableTCPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.output_stream_url: str = ""
        self.detected_box: StreamerBox | None = None
        self.streamer_auto_detected: bool = False
        self.last_error: str = ""

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _yt_dlp_prefix(self) -> list[str]:
        found = shutil.which("yt-dlp")
        if found:
            return [found]
        scripts_exe = Path(sys.executable).resolve().parent / (
            "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
        )
        if scripts_exe.is_file():
            return [str(scripts_exe)]
        return [sys.executable, "-m", "yt_dlp"]

    def _resolve_live_media_url(self, stream_url: str) -> str:
        format_selectors = [
            "best",
            "bv*+ba/b",
            "95/94/93/96/92/91/best",
        ]
        last_stderr = ""

        for fmt in format_selectors:
            cmd = [
                *self._yt_dlp_prefix(),
                "--no-warnings",
                "--no-playlist",
                "-f",
                fmt,
                "-g",
                stream_url,
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            urls = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            if res.returncode == 0 and urls:
                return urls[0]
            last_stderr = res.stderr[-1200:]

        raise LiveStreamError(
            f"Unable to resolve live stream URL:\n{last_stderr}"
        )

    def grab_multi_pass_snapshots(
        self, ffmpeg: str, media_url: str, out_dir: Path, count: int = 3
    ) -> list[Path]:
        """Grab a short multi-frame sample from the live stream for multi-pass detection."""
        pattern = out_dir / "snap_%02d.jpg"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-live_start_index",
            "-1",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            media_url,
            "-t",
            str(max(2, count)),
            "-vf",
            "fps=1",
            "-q:v",
            "3",
            "-y",
            str(pattern),
        ]
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            log.warning("Multi-pass snapshot grab timed out; using available frames or fallback.")
        return sorted(out_dir.glob("snap_*.jpg"))

    def grab_full_frame_png(self, source_stream_url: str) -> bytes | None:
        """Grab a single live frame from source_stream_url and return it as PNG bytes."""
        url = (source_stream_url or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise LiveStreamError(
                "Enter a valid live YouTube stream URL starting with http:// or https://."
            )
        ffmpeg = find_ffmpeg(self.ffmpeg_path)
        media_url = self._resolve_live_media_url(url)

        with tempfile.TemporaryDirectory(prefix="clipforge_full_") as tmp_dir:
            snap_path = Path(tmp_dir) / "full_frame.jpg"
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-live_start_index",
                "-1",
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
                "-i",
                media_url,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(snap_path),
            ]
            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=25,
                )
            except subprocess.TimeoutExpired:
                return None

            if not snap_path.is_file() or snap_path.stat().st_size == 0:
                return None

            try:
                import cv2

                frame = cv2.imread(str(snap_path))
                if frame is not None and frame.size > 0:
                    ok, enc = cv2.imencode(".png", frame)
                    if ok:
                        return enc.tobytes()
            except ImportError:
                pass

            return snap_path.read_bytes()

    def detect_from_source_url(self, source_stream_url: str) -> tuple[StreamerBox, bool]:
        """Resolve source stream, sample frames, and run multi-pass streamer detection."""
        url = (source_stream_url or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise LiveStreamError(
                "Enter a valid live YouTube stream URL starting with http:// or https://."
            )
        ffmpeg = find_ffmpeg(self.ffmpeg_path)
        media_url = self._resolve_live_media_url(url)

        with tempfile.TemporaryDirectory(prefix="clipforge_snap_") as tmp_dir:
            snaps = self.grab_multi_pass_snapshots(ffmpeg, media_url, Path(tmp_dir), count=3)
            box, found = detect_streamer_box_multi_pass(snaps)

        self.detected_box = box
        self.streamer_auto_detected = found
        return box, found

    def detect_with_preview_from_source_url(
        self, source_stream_url: str
    ) -> tuple[StreamerBox, bool, bytes | None]:
        """Resolve stream, run multi-pass detection, and return (box, detected, preview_png_bytes)."""
        url = (source_stream_url or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise LiveStreamError(
                "Enter a valid live YouTube stream URL starting with http:// or https://."
            )
        ffmpeg = find_ffmpeg(self.ffmpeg_path)
        media_url = self._resolve_live_media_url(url)

        preview_bytes: bytes | None = None
        with tempfile.TemporaryDirectory(prefix="clipforge_snap_") as tmp_dir:
            snaps = self.grab_multi_pass_snapshots(ffmpeg, media_url, Path(tmp_dir), count=3)
            box, found = detect_streamer_box_multi_pass(snaps)
            if snaps:
                preview_bytes = render_detection_preview_bytes(snaps[-1], box, found)

        self.detected_box = box
        self.streamer_auto_detected = found
        return box, found, preview_bytes

    def _start_local_sample_server(self, serve_dir: Path, port: int) -> str:
        serve_dir.mkdir(parents=True, exist_ok=True)
        if self._httpd is not None:
            return f"http://localhost:{port}/live_shorts/index.m3u8"

        handler = functools.partial(_QuietHLSHandler, directory=str(serve_dir.parent))
        httpd = _ReusableTCPServer((DEFAULT_SAMPLE_HOST, port), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self._httpd = httpd
        self._http_thread = thread
        return f"http://localhost:{port}/live_shorts/index.m3u8"

    def _build_vertical_filter(self, top_ratio: float, box: StreamerBox) -> str:
        """Build 1080x1920 filtergraph: streamer on top, gameplay on bottom."""
        clamped_ratio = min(max(top_ratio, 0.2), 0.7)
        top_h = int(round(1920 * clamped_ratio))
        top_h -= top_h % 2
        bot_h = 1920 - top_h

        bx = min(max(box.x, 0.0), 0.9)
        by = min(max(box.y, 0.0), 0.9)
        bw = min(max(box.w, 0.05), 1.0 - bx)
        bh = min(max(box.h, 0.05), 1.0 - by)

        crop_w = f"iw*{bw:.4f}"
        crop_h = f"ih*{bh:.4f}"
        crop_x = f"iw*{bx:.4f}"
        crop_y = f"ih*{by:.4f}"

        return (
            f"[0:v]split=2[v_top][v_bot];"
            f"[v_top]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
            f"scale=1080:{top_h}:force_original_aspect_ratio=increase,"
            f"crop=1080:{top_h},setsar=1[top];"
            f"[v_bot]crop=iw:ih*0.85:0:ih*0.15,"
            f"scale=1080:{bot_h}:force_original_aspect_ratio=increase,"
            f"crop=1080:{bot_h},setsar=1[bot];"
            f"[top][bot]vstack=inputs=2,format=yuv420p[vout]"
        )

    def start(self, cfg: LiveRelayConfig) -> str:
        """Start continuous vertical reformatting and return the active output stream link."""
        if self.is_running:
            return self.output_stream_url

        url = (cfg.source_stream_url or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise LiveStreamError(
                "Enter a valid live YouTube stream URL starting with http:// or https://."
            )

        self.last_error = ""
        self._stop_event.clear()
        ffmpeg = find_ffmpeg(self.ffmpeg_path)
        media_url = self._resolve_live_media_url(url)

        if cfg.streamer_box is not None:
            active_box = cfg.streamer_box
            self.streamer_auto_detected = False
        elif cfg.auto_detect_streamer:
            with tempfile.TemporaryDirectory(prefix="clipforge_snap_") as tmp_dir:
                snaps = self.grab_multi_pass_snapshots(ffmpeg, media_url, Path(tmp_dir), count=3)
                active_box, found = detect_streamer_box_multi_pass(snaps)
            self.streamer_auto_detected = found
        else:
            active_box = StreamerBox(0.0, 0.0, 0.40, 0.35)
            self.streamer_auto_detected = False

        self.detected_box = active_box
        filter_complex = self._build_vertical_filter(cfg.top_ratio, active_box)

        cmd: list[str] = [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "warning",
            "-re",
            "-live_start_index",
            "-1",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            media_url,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-r",
            "30",
            "-g",
            "60",
            "-b:v",
            "3500k",
            "-maxrate",
            "3500k",
            "-bufsize",
            "7000k",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
        ]

        custom_target = (cfg.target_url or "").strip()
        if custom_target:
            if custom_target.lower().startswith(("rtmp://", "rtmps://")):
                cmd.extend(["-f", "flv", custom_target])
            else:
                hls_dir = Path(cfg.relay_dir) / "live_shorts"
                hls_dir.mkdir(parents=True, exist_ok=True)
                playlist = hls_dir / "index.m3u8"
                cmd.extend([
                    "-f",
                    "hls",
                    "-hls_time",
                    "2",
                    "-hls_list_size",
                    "6",
                    "-hls_flags",
                    "delete_segments+append_list",
                    str(playlist),
                ])
            self.output_stream_url = custom_target
        else:
            hls_dir = Path(cfg.relay_dir) / "live_shorts"
            hls_dir.mkdir(parents=True, exist_ok=True)
            for old_file in hls_dir.glob("*"):
                old_file.unlink(missing_ok=True)
            playlist = hls_dir / "index.m3u8"
            self.output_stream_url = self._start_local_sample_server(hls_dir, cfg.sample_port)
            cmd.extend([
                "-f",
                "hls",
                "-hls_time",
                "2",
                "-hls_list_size",
                "6",
                "-hls_flags",
                "delete_segments+append_list",
                str(playlist),
            ])

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        time.sleep(0.8)
        if self._proc.poll() is not None:
            err = self._proc.stderr.read() if self._proc.stderr else ""
            self.last_error = err[-1500:]
            self._proc = None
            raise LiveStreamError(f"Live vertical relay exited immediately:\n{self.last_error}")

        return self.output_stream_url

    def stop(self) -> None:
        """Stop the active FFmpeg relay process cleanly."""
        self._stop_event.set()
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()