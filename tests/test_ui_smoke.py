"""End-to-end UI tests using Streamlit's headless AppTest (no browser, no network)."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from conftest import GOOD_CLIP, FakeClient, make_rows  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_app_starts_cleanly():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value.endswith("ClipForge AI")
    assert any("Extract a transcript" in i.value for i in at.info)


def test_invalid_url_shows_error():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("https://example.com/nope").run()
    button(at, "1. Extract transcript").click().run()
    assert not at.exception
    assert any("Invalid YouTube video URL" in e.value for e in at.error)


def test_analyze_without_transcript_warns():
    at = AppTest.from_file(APP, default_timeout=30).run()
    button(at, "2. Find clip moments").click().run()
    assert any("Extract a transcript first" in w.value for w in at.warning)


def test_full_flow_with_fakes(monkeypatch):
    rows = make_rows(special={100: GOOD_CLIP["evidence"]})
    import clipforge.ui.main as main_module

    monkeypatch.setattr(main_module, "fetch_transcript", lambda vid, langs: rows)
    monkeypatch.setattr(main_module, "OllamaClient", lambda *a, **k: FakeClient([{"clips": [GOOD_CLIP]}]))

    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("https://youtu.be/dQw4w9WgXcQ").run()
    button(at, "1. Extract transcript").click().run()
    assert not at.exception
    assert any("Successfully extracted 60" in s.value for s in at.success)
    assert at.session_state.video_id == "dQw4w9WgXcQ"

    button(at, "2. Find clip moments").click().run()
    assert not at.exception, at.exception
    assert len(at.session_state.clips) == 1
    assert any("Found 1 supported clip" in s.value for s in at.success)

    # Render section appears; render button is disabled until a video is uploaded.
    render = button(at, "Render approved clips as vertical MP4s")
    assert render.disabled

    # Manual layout with out-of-frame facecam disables rendering.
    at.radio(key="layout_mode").set_value("Manual").run()
    at.selectbox(key="selected_layout").set_value("Floating facecam").run()
    at.slider(key="facecam_x").set_value(90).run()
    assert any("outside the video boundary" in e.value for e in at.error)


def test_ai_failure_is_reported_not_crashing(monkeypatch):
    from clipforge.errors import OllamaError
    import clipforge.ui.main as main_module

    monkeypatch.setattr(main_module, "fetch_transcript", lambda vid, langs: make_rows())
    monkeypatch.setattr(main_module, "OllamaClient", lambda *a, **k: FakeClient([OllamaError("server down")]))

    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("https://youtu.be/dQw4w9WgXcQ").run()
    button(at, "1. Extract transcript").click().run()
    button(at, "2. Find clip moments").click().run()
    assert not at.exception
    assert any("server down" in e.value for e in at.error)
    assert at.session_state.clips == []
