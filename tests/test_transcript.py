import pytest

from clipforge.errors import TranscriptError
from clipforge.transcript.chunking import split_into_chunks
from clipforge.transcript.formatting import format_row_for_ai, to_plain_text
from clipforge.transcript.youtube import get_video_id
from conftest import make_rows

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=30s",
    f"https://m.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?si=abc",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/live/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"  https://www.youtube.com/watch?v={VID}  ",
])
def test_valid_urls(url):
    assert get_video_id(url) == VID


@pytest.mark.parametrize("url", [
    "", "not a url", "https://example.com/watch?v=" + VID,
    "https://www.youtube.com/watch?v=short", "https://www.youtube.com/watch",
    "https://www.youtube.com/channel/abc", "https://evil.com/youtu.be/" + VID,
])
def test_invalid_urls(url):
    with pytest.raises(TranscriptError):
        get_video_id(url)


def test_formatting():
    row = {"start_sec": 65.0, "end_sec": 70.5, "text": "hello"}
    assert format_row_for_ai(row) == "[start_sec=65.00, end_sec=70.50, 01:05-01:10] hello"
    assert to_plain_text([{"start_sec": 5, "text": "hi"}]) == "[00:05] hi"


def test_chunking_empty():
    assert split_into_chunks([]) == []


def test_chunking_single_chunk():
    chunks = split_into_chunks(make_rows(30), max_chars=10_000)
    assert len(chunks) == 1
    assert chunks[0]["start_sec"] == 0 and chunks[0]["end_sec"] == 30


def test_chunking_size_coverage_and_overlap():
    rows = make_rows(1200)
    chunks = split_into_chunks(rows, max_chars=1500, overlap_seconds=30)
    assert len(chunks) > 3
    assert all(len(c["text"]) <= 1500 for c in chunks)
    covered = {r["start_sec"] for c in chunks for r in c["rows"]}
    assert covered == {r["start_sec"] for r in rows}      # nothing lost
    for a, b in zip(chunks, chunks[1:]):
        assert b["start_sec"] < a["end_sec"]               # they overlap
        assert b["start_sec"] > a["start_sec"]             # and make progress


def test_chunking_oversized_single_row_terminates():
    rows = [{"start_sec": 0.0, "end_sec": 5.0, "text": "x" * 500}]
    assert len(split_into_chunks(rows, max_chars=100)) == 1


# ---------- fetch_transcript (library mocked; no network) ----------

def _snippet(text, start, duration):
    from youtube_transcript_api import FetchedTranscriptSnippet
    return FetchedTranscriptSnippet(text=text, start=start, duration=duration)


def _patch_api(monkeypatch, fetch):
    pytest.importorskip("youtube_transcript_api")
    import youtube_transcript_api

    class FakeApi:
        def fetch(self, video_id, languages):
            return fetch(video_id, languages)

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApi)


def test_fetch_transcript_cleans_and_sorts(monkeypatch):
    from clipforge.transcript.youtube import fetch_transcript
    seen = {}

    def fetch(video_id, languages):
        seen["args"] = (video_id, languages)
        return [_snippet("second\nline", 10.123, 2.0), _snippet("   ", 5, 1), _snippet("first", 1, 3.5)]

    _patch_api(monkeypatch, fetch)
    rows = fetch_transcript(VID, ["en-US", "en"])
    assert seen["args"] == (VID, ["en-US", "en"])
    assert [r["text"] for r in rows] == ["first", "second line"]     # blank dropped, sorted, newline removed
    assert rows[1] == {"start_sec": 10.12, "end_sec": 12.12, "timestamp": "00:10", "text": "second line"}


def test_fetch_transcript_wraps_library_errors(monkeypatch):
    from clipforge.transcript.youtube import fetch_transcript

    def fetch(video_id, languages):
        raise RuntimeError("Subtitles are disabled for this video")

    _patch_api(monkeypatch, fetch)
    with pytest.raises(TranscriptError, match="Subtitles are disabled"):
        fetch_transcript(VID, ["en"])


def test_fetch_transcript_empty(monkeypatch):
    from clipforge.transcript.youtube import fetch_transcript
    _patch_api(monkeypatch, lambda v, l: [_snippet("  ", 0, 1)])
    with pytest.raises(TranscriptError, match="No transcript segments"):
        fetch_transcript(VID, ["en"])
