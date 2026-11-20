import pytest

from clipforge.ai.analyzer import analyze_transcript
from clipforge.errors import AnalysisError, OllamaError
from conftest import GOOD_CLIP, FakeClient, make_rows


def test_happy_path(rows):
    seen = []
    result = analyze_transcript(
        rows, FakeClient([{"clips": [GOOD_CLIP]}]), 5, 15, 60,
        progress_callback=lambda d, t: seen.append((d, t)),
    )
    assert len(result.clips) == 1          # duplicates across chunks removed
    assert result.chunks_failed == 0
    assert seen and seen[-1][0] == seen[-1][1]


def test_clip_count_limit_and_ranking():
    rows = make_rows(300, special={
        20: "first amazing words spoken right here", 100: "second amazing words spoken right here",
        200: "third amazing words spoken right here",
    })
    replies = {"clips": [
        {**GOOD_CLIP, "start_sec": s, "end_sec": s + 8, "score": sc,
         "title": f"Moment number {s}", "evidence": txt}
        for s, sc, txt in [(20, 5, "first amazing words spoken right here"),
                           (100, 9, "second amazing words spoken right here"),
                           (200, 7, "third amazing words spoken right here")]
    ]}
    result = analyze_transcript(rows, FakeClient([replies]), 2, 15, 60, max_chunk_chars=50_000)
    assert [c["score"] for c in result.clips] == [9, 7]


def test_retry_after_failure(rows):
    client = FakeClient([OllamaError("boom"), {"clips": [GOOD_CLIP]}])
    result = analyze_transcript(rows, client, 5, 15, 60, max_chunk_chars=50_000)
    assert len(result.clips) == 1 and client.calls == 2


def test_all_requests_fail_reports_real_cause(rows):
    with pytest.raises(AnalysisError, match="connection refused"):
        analyze_transcript(rows, FakeClient([OllamaError("connection refused")]), 5, 15, 60)


def test_no_supported_candidates(rows):
    bad = {**GOOD_CLIP, "evidence": "nothing of the sort was ever said here"}
    with pytest.raises(AnalysisError, match="unsupported_evidence"):
        analyze_transcript(rows, FakeClient([{"clips": [bad]}]), 5, 15, 60)


def test_input_validation(rows):
    with pytest.raises(ValueError):
        analyze_transcript([], FakeClient([]), 5, 15, 60)
    with pytest.raises(ValueError):
        analyze_transcript(rows, FakeClient([]), 5, 60, 30)
