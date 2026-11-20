import io
import json
import shutil
import subprocess
import zipfile

import pytest

from clipforge.errors import RenderError
from clipforge.rendering import layouts
from clipforge.rendering.ffmpeg import find_ffmpeg
from clipforge.rendering.regions import region_crop_filter, validate_region
from clipforge.rendering.renderer import render_clips, safe_filename, validate_render_clips

FACE = {"x": 70, "y": 5, "width": 25, "height": 30}
GAME = {"x": 0, "y": 15, "width": 100, "height": 85}


# ---------- pure logic ----------

def test_validate_region_ok():
    assert validate_region(FACE, "facecam") == {"x": 70.0, "y": 5.0, "width": 25.0, "height": 30.0}


@pytest.mark.parametrize("region", [
    None, "x", {}, {"x": 0, "y": 0, "width": 0, "height": 10},
    {"x": 90, "y": 0, "width": 20, "height": 10}, {"x": -1, "y": 0, "width": 5, "height": 5},
    {"x": "a", "y": 0, "width": 5, "height": 5},
])
def test_validate_region_rejects(region):
    with pytest.raises(RenderError):
        validate_region(region, "facecam")


def test_region_error_names_the_region():
    with pytest.raises(RenderError, match="gameplay"):
        region_crop_filter(None, "gameplay")


def test_crop_filter_format():
    assert region_crop_filter(FACE) == "crop=iw*0.250000:ih*0.300000:iw*0.700000:ih*0.050000"


def test_filters_have_output_label():
    for layout in (layouts.BLURRED, layouts.FULLSCREEN):
        assert layouts.build_video_filter(layout).endswith("[v]")
    assert layouts.build_video_filter(layouts.FACECAM_GAMEPLAY, FACE, 30, GAME).endswith("[v]")
    assert layouts.build_video_filter(layouts.FLOATING_FACECAM, FACE).endswith("[v]")


def test_split_ratio_heights_add_up_to_1920():
    f = layouts.build_video_filter(layouts.FACECAM_GAMEPLAY, FACE, 30, GAME)
    assert "1080:576" in f and "1080:1344" in f      # 30% / 70% of 1920
    assert "lanczos" in f
    assert "vstack=inputs=2" in f


@pytest.mark.parametrize("ratio", [10, 60, "abc", None])
def test_bad_split_ratio(ratio):
    with pytest.raises(RenderError):
        layouts.build_video_filter(layouts.FACECAM_GAMEPLAY, FACE, ratio, GAME)


def test_layouts_require_regions_and_known_name():
    with pytest.raises(RenderError):
        layouts.build_video_filter(layouts.FACECAM_GAMEPLAY, FACE, 30, None)
    with pytest.raises(RenderError):
        layouts.build_video_filter(layouts.FLOATING_FACECAM, None)
    with pytest.raises(RenderError, match="Unsupported"):
        layouts.build_video_filter("Nope")


def test_validate_render_clips():
    ok = validate_render_clips([
        {"start_sec": 1, "end_sec": 20, "title": "A"},
        {"start_sec": "2.5", "end_sec": 30, "title": float("nan")},   # NaN title from a table cell
    ])
    assert ok[1]["title"] == "highlight" and ok[1]["start_sec"] == 2.5


@pytest.mark.parametrize("row", [
    {"start_sec": None, "end_sec": 5}, {"start_sec": -1, "end_sec": 5},
    {"start_sec": 5, "end_sec": 5}, {"start_sec": 5, "end_sec": 5.5},
])
def test_validate_render_clips_rejects(row):
    with pytest.raises(RenderError):
        validate_render_clips([row])


def test_validate_render_clips_empty():
    with pytest.raises(RenderError):
        validate_render_clips([])


def test_safe_filename():
    assert safe_filename(3, "Boss: explodes?! <now>") == "clip_03_Boss_explodes_now.mp4"
    assert safe_filename(1, "???") == "clip_01_highlight.mp4"
    assert len(safe_filename(1, "x" * 200)) <= len("clip_01_.mp4") + 35


def test_find_ffmpeg_errors(monkeypatch):
    with pytest.raises(RenderError, match="not found"):
        find_ffmpeg("definitely-not-a-real-ffmpeg-binary")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RenderError, match="FFmpeg was not found"):
        find_ffmpeg("")


def test_missing_source(tmp_path):
    with pytest.raises(RenderError, match="source video"):
        render_clips(tmp_path / "nope.mp4", [{"start_sec": 0, "end_sec": 5, "title": "x"}], {})


# ---------- real FFmpeg ----------

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


@pytest.fixture(scope="module")
def source_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("src") / "source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return path


def probe(path):
    out = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
        "-show_entries", "format=duration", "-of", "json", str(path),
    ], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


CLIPS = [
    {"start_sec": 0.5, "end_sec": 3.5, "title": "First clip"},
    {"start_sec": 2.0, "end_sec": 5.0, "title": "Second: clip!"},
]

LAYOUT_CASES = [
    {"layout": layouts.BLURRED},
    {"layout": layouts.FULLSCREEN},
    {"layout": layouts.FACECAM_GAMEPLAY, "facecam_region": FACE, "gameplay_region": GAME, "split_ratio": 30},
    {"layout": layouts.FLOATING_FACECAM, "facecam_region": FACE},
]


@needs_ffmpeg
@pytest.mark.parametrize("settings", LAYOUT_CASES, ids=[c["layout"] for c in LAYOUT_CASES])
def test_render_every_layout(source_video, tmp_path, settings):
    calls = []
    data = render_clips(source_video, CLIPS, settings, progress_callback=lambda d, t: calls.append((d, t)))
    assert calls == [(1, 2), (2, 2)]

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == ["clip_01_First_clip.mp4", "clip_02_Second_clip.mp4"]
        zf.extractall(tmp_path)

    for name in zf.namelist():
        info = probe(tmp_path / name)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert (video["width"], video["height"]) == (1080, 1920)
        assert any(s["codec_type"] == "audio" for s in info["streams"])
        assert 2.5 < float(info["format"]["duration"]) < 3.5


@needs_ffmpeg
def test_render_reports_ffmpeg_failure(tmp_path):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"this is not a video")
    with pytest.raises(RenderError, match="Clip 1"):
        render_clips(bogus, CLIPS[:1], {"layout": layouts.BLURRED})


@needs_ffmpeg
def test_render_start_beyond_video_end_is_an_error(source_video):
    with pytest.raises(RenderError):
        render_clips(source_video, [{"start_sec": 500, "end_sec": 520, "title": "late"}],
                     {"layout": layouts.FULLSCREEN})


# ---------- automatic facecam detection & high-quality rendering ----------

def test_expand_face_to_facecam_region():
    from clipforge.rendering.facecam_detector import expand_face_to_facecam_region

    region = expand_face_to_facecam_region(75.0, 10.0, 10.0, 12.0)
    assert 0.0 <= region["x"] and region["x"] + region["width"] <= 100.0
    assert 0.0 <= region["y"] and region["y"] + region["height"] <= 100.0
    assert region["width"] >= 16.0
    assert region["height"] >= 16.0


def test_detect_facecam_region_with_fake_sampler(tmp_path):
    from clipforge.rendering.facecam_detector import detect_facecam_region

    vid = tmp_path / "sample.mp4"
    vid.write_bytes(b"fake video bytes")

    def fake_sampler(_path, _n):
        # Streamer face on left-side facecam overlay (~x=12%, y=45%, w=7%, h=8%)
        return [
            (1920, 1080, [(12.0, 45.0, 7.0, 8.0)]),
            (1920, 1080, [(12.2, 45.2, 7.0, 8.0)]),
            (1920, 1080, [(11.8, 44.8, 7.1, 8.1)]),
            (1920, 1080, []),
        ]

    res = detect_facecam_region(vid, sample_frames=4, min_confidence=0.5, sampler=fake_sampler)
    assert res.detected is True
    assert res.confidence == 0.75
    assert res.matched_frames == 3
    assert res.region["x"] < 20.0


def test_detect_facecam_region_fallback_when_no_face(tmp_path):
    from clipforge.rendering.facecam_detector import DEFAULT_FACECAM_REGION, detect_facecam_region

    vid = tmp_path / "sample.mp4"
    vid.write_bytes(b"fake video bytes")

    def no_face_sampler(_path, _n):
        return [(1280, 720, []) for _ in range(5)]

    res = detect_facecam_region(vid, sample_frames=5, min_confidence=0.25, sampler=no_face_sampler)
    assert res.detected is False
    assert res.confidence == 0.0
    assert res.region == DEFAULT_FACECAM_REGION


def test_resolve_layout_settings_auto_facecam_gameplay(tmp_path):
    from clipforge.rendering.renderer import resolve_layout_settings

    vid = tmp_path / "sample.mp4"
    vid.write_bytes(b"fake video bytes")

    def sampler(_path, _n):
        return [(1280, 720, [(75.0, 10.0, 8.0, 10.0)]) for _ in range(4)]

    resolved = resolve_layout_settings(
        vid,
        {"layout": layouts.FACECAM_GAMEPLAY, "auto_detect_facecam": True, "split_ratio": 35},
        sample_frames=4,
        min_confidence=0.25,
        sampler=sampler,
    )
    assert resolved["facecam_detected"] is True
    assert resolved["facecam_region"] is not None
    assert resolved["gameplay_region"] == {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0}
