"""Automatic facecam / streamer space detection across the full stream area.

Scans the entire source frame to locate the streamer's face, auto-adjusts the
crop box to the surrounding webcam overlay edges when present, and returns a
percentage crop ``{"x", "y", "width", "height"}`` that fills the top band.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from clipforge.errors import RenderError

log = logging.getLogger(__name__)

DEFAULT_FACECAM_REGION: dict[str, float] = {
    "x": 0.5,
    "y": 44.0,
    "width": 19.5,
    "height": 13.5,
}

FrameSampler = Callable[[Path, int], list[tuple[int, int, list[tuple[float, float, float, float]]]]]


@dataclass(frozen=True)
class FacecamDetectionResult:
    """Result of automatic streamer/facecam detection across the stream area."""

    region: dict[str, float]
    detected: bool
    confidence: float
    sample_count: int
    matched_frames: int


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def expand_face_to_facecam_region(
    fx: float,
    fy: float,
    fw: float,
    fh: float,
    *,
    width_scale: float = 1.75,
    height_scale: float = 1.9,
    y_offset_ratio: float = 0.55,
    min_width: float = 12.0,
    min_height: float = 11.0,
    max_width: float = 34.0,
    max_height: float = 32.0,
) -> dict[str, float]:
    """Auto-adjust detected face bounds ``(fx, fy, fw, fh)`` (0..100%) into a webcam crop."""
    cam_w = _clamp(fw * width_scale, min_width, max_width)
    cam_h = _clamp(fh * height_scale, min_height, max_height)

    center_x = fx + fw / 2.0
    center_y = fy + fh * y_offset_ratio

    x = _clamp(center_x - cam_w / 2.0, 0.0, 100.0 - cam_w)
    y = _clamp(center_y - cam_h / 2.0, 0.0, 100.0 - cam_h)

    cam_w = min(cam_w, 100.0 - x)
    cam_h = min(cam_h, 100.0 - y)

    return {
        "x": round(x, 2),
        "y": round(y, 2),
        "width": round(cam_w, 2),
        "height": round(cam_h, 2),
    }


def _snap_to_webcam_overlay(
    cv2_mod,
    frame,
    face_box: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Auto-adjust around a detected face box to match nearby rectangular webcam borders."""
    h, w = frame.shape[:2]
    fx_pct, fy_pct, fw_pct, fh_pct = face_box
    base = expand_face_to_facecam_region(fx_pct, fy_pct, fw_pct, fh_pct)

    if not hasattr(cv2_mod, "findContours") or w <= 0 or h <= 0:
        return base["x"], base["y"], base["width"], base["height"]

    gray = cv2_mod.cvtColor(frame, cv2_mod.COLOR_BGR2GRAY)
    edges = cv2_mod.Canny(gray, 50, 150)
    kernel = cv2_mod.getStructuringElement(cv2_mod.MORPH_RECT, (5, 5))
    closed = cv2_mod.morphologyEx(edges, cv2_mod.MORPH_CLOSE, kernel)
    contours_info = cv2_mod.findContours(closed, cv2_mod.RETR_EXTERNAL, cv2_mod.CHAIN_APPROX_SIMPLE)
    contours = contours_info[0] if isinstance(contours_info, tuple) else contours_info

    face_cx = (fx_pct + fw_pct / 2.0) / 100.0 * w
    face_cy = (fy_pct + fh_pct / 2.0) / 100.0 * h
    face_w_px = (fw_pct / 100.0) * w
    face_h_px = (fh_pct / 100.0) * h

    best_box = None
    best_score = float("inf")

    for cnt in contours:
        bx, by, bw, bh = cv2_mod.boundingRect(cnt)
        if bw < face_w_px * 1.1 or bh < face_h_px * 1.1:
            continue
        if bw > w * 0.45 or bh > h * 0.55:
            continue
        if bx <= face_cx <= bx + bw and by <= face_cy <= by + bh:
            box_cx = bx + bw / 2.0
            box_cy = by + bh / 2.0
            dist = ((box_cx - face_cx) ** 2 + (box_cy - face_cy) ** 2) ** 0.5
            area_penalty = (bw * bh) / float(w * h)
            score = dist + area_penalty * 200.0
            if score < best_score:
                best_score = score
                best_box = (
                    (bx / w) * 100.0,
                    (by / h) * 100.0,
                    (bw / w) * 100.0,
                    (bh / h) * 100.0,
                )

    if best_box is None:
        return base["x"], base["y"], base["width"], base["height"]

    sx, sy, sw, sh = best_box
    sw = _clamp(sw, 12.0, 38.0)
    sh = _clamp(sh, 11.0, 36.0)
    sx = _clamp(sx, 0.0, 100.0 - sw)
    sy = _clamp(sy, 0.0, 100.0 - sh)
    return round(sx, 2), round(sy, 2), round(sw, 2), round(sh, 2)


def _aggregate_detections(
    frame_detections: list[tuple[int, int, list[tuple[float, float, float, float]]]],
    min_confidence: float = 0.15,
) -> FacecamDetectionResult:
    """Aggregate auto-adjusted webcam regions across sampled frames."""
    total_samples = len(frame_detections)
    if total_samples == 0:
        return FacecamDetectionResult(
            region=dict(DEFAULT_FACECAM_REGION),
            detected=False,
            confidence=0.0,
            sample_count=0,
            matched_frames=0,
        )

    candidates: list[tuple[float, float, float, float]] = []
    for _w, _h, boxes in frame_detections:
        if not boxes:
            continue
        plausible = [b for b in boxes if b[2] <= 45.0 and b[3] <= 50.0]
        pool = plausible if plausible else boxes
        best_box = max(pool, key=lambda b: b[2] * b[3])
        candidates.append(best_box)

    matched = len(candidates)
    confidence = matched / total_samples if total_samples > 0 else 0.0

    if not candidates or confidence < min_confidence:
        return FacecamDetectionResult(
            region=dict(DEFAULT_FACECAM_REGION),
            detected=False,
            confidence=round(confidence, 3),
            sample_count=total_samples,
            matched_frames=matched,
        )

    if len(candidates) >= 3:
        med_cx = sorted(b[0] + b[2] / 2.0 for b in candidates)[len(candidates) // 2]
        med_cy = sorted(b[1] + b[3] / 2.0 for b in candidates)[len(candidates) // 2]
        inliers = [
            b for b in candidates
            if abs((b[0] + b[2] / 2.0) - med_cx) <= 28.0
            and abs((b[1] + b[3] / 2.0) - med_cy) <= 28.0
        ]
        if inliers:
            candidates = inliers

    avg_x = sum(b[0] for b in candidates) / len(candidates)
    avg_y = sum(b[1] for b in candidates) / len(candidates)
    avg_w = sum(b[2] for b in candidates) / len(candidates)
    avg_h = sum(b[3] for b in candidates) / len(candidates)

    region = {
        "x": round(_clamp(avg_x, 0.0, 95.0), 2),
        "y": round(_clamp(avg_y, 0.0, 95.0), 2),
        "width": round(_clamp(avg_w, 12.0, 100.0 - _clamp(avg_x, 0.0, 95.0)), 2),
        "height": round(_clamp(avg_h, 11.0, 100.0 - _clamp(avg_y, 0.0, 95.0)), 2),
    }
    return FacecamDetectionResult(
        region=region,
        detected=True,
        confidence=round(confidence, 3),
        sample_count=total_samples,
        matched_frames=matched,
    )


def _load_cascades(cv2_mod) -> list:
    if not hasattr(cv2_mod, "CascadeClassifier") or getattr(cv2_mod, "data", None) is None:
        return []
    cascade_dir = Path(cv2_mod.data.haarcascades)
    names = [
        "haarcascade_frontalface_default.xml",
        "haarcascade_frontalface_alt2.xml",
        "haarcascade_profileface.xml",
    ]
    loaded = []
    for name in names:
        p = cascade_dir / name
        if p.is_file():
            clf = cv2_mod.CascadeClassifier(str(p))
            if not clf.empty():
                loaded.append(clf)
    return loaded


def _detect_faces_in_frame(cv2_mod, cascades: list, frame) -> list[tuple[float, float, float, float]]:
    """Detect faces across the full frame and auto-adjust each box to its webcam overlay."""
    h, w = frame.shape[:2]
    if w <= 0 or h <= 0 or not cascades:
        return []

    gray = cv2_mod.cvtColor(frame, cv2_mod.COLOR_BGR2GRAY)
    gray_eq = cv2_mod.equalizeHist(gray)
    min_dim = min(w, h)

    adjusted_boxes: list[tuple[float, float, float, float]] = []
    for clf in cascades:
        rects = clf.detectMultiScale(
            gray_eq,
            scaleFactor=1.06,
            minNeighbors=3,
            minSize=(max(16, int(min_dim * 0.02)), max(16, int(min_dim * 0.02))),
        )
        for (fx, fy, fw, fh) in rects:
            face_pct = (
                (fx / w) * 100.0,
                (fy / h) * 100.0,
                (fw / w) * 100.0,
                (fh / h) * 100.0,
            )
            adjusted_boxes.append(_snap_to_webcam_overlay(cv2_mod, frame, face_pct))

    return adjusted_boxes


def _sample_faces_opencv(video_path: Path, sample_frames: int) -> list[tuple[int, int, list[tuple[float, float, float, float]]]]:
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise RenderError(
            "Automatic face detection requires OpenCV (opencv-python). "
            "Install it or switch to Manual layout mode."
        ) from exc

    cascades = _load_cascades(cv2)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RenderError("Could not open source video for automatic facecam detection.")

    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        n_samples = max(1, sample_frames)
        if frame_count > 0:
            indices = sorted({
                int(i * (frame_count - 1) / max(1, n_samples - 1))
                for i in range(n_samples)
            })
        else:
            indices = list(range(n_samples))

        results: list[tuple[int, int, list[tuple[float, float, float, float]]]] = []
        target_set = set(indices)
        max_idx = max(indices) if indices else 0
        current_idx = 0

        while current_idx <= max_idx:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if current_idx in target_set:
                h, w = frame.shape[:2]
                pct_boxes = _detect_faces_in_frame(cv2, cascades, frame)
                results.append((w, h, pct_boxes))
            current_idx += 1

        return results
    finally:
        cap.release()


def detect_facecam_region(
    video_path: Path | str,
    *,
    sample_frames: int = 24,
    min_confidence: float = 0.15,
    sampler: FrameSampler | None = None,
) -> FacecamDetectionResult:
    """Detect and auto-adjust the streamer's facecam region across the stream video."""
    path = Path(video_path)
    if not path.is_file():
        raise RenderError("Please provide a source video.")
    if sample_frames < 1:
        raise RenderError("Facecam sample frame count must be at least 1.")

    frame_sampler = sampler or _sample_faces_opencv
    detections = frame_sampler(path, sample_frames)
    result = _aggregate_detections(detections, min_confidence=min_confidence)
    log.info(
        "Facecam detection finished: detected=%s region=%s confidence=%.2f (%d/%d frames)",
        result.detected,
        result.region,
        result.confidence,
        result.matched_frames,
        result.sample_count,
    )
    return result