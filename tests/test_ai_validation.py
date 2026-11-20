from clipforge.ai import validation as v
from clipforge.ai.dedup import remove_duplicate_clips
from clipforge.ai.evidence import verify_evidence
from conftest import GOOD_CLIP

CHUNK = {"start_sec": 0.0, "end_sec": 300.0}


def validate(rows, **overrides):
    clip = {**GOOD_CLIP, **overrides}
    return v.validate_clip(clip, CHUNK, rows, 300.0, 15, 60)


def test_evidence_found(rows):
    assert verify_evidence(GOOD_CLIP["evidence"], rows, 100, 108) == 1.0


def test_evidence_missing_or_short(rows):
    assert verify_evidence("", rows, 100, 108) == 0.0
    assert verify_evidence("hi", rows, 100, 108) == 0.0
    assert verify_evidence("completely invented quote about dragons", rows, 100, 108) < 0.35


def test_good_clip_is_expanded_evenly(rows):
    clip, reason = validate(rows)
    assert reason is None
    assert clip["duration_sec"] == 15.0
    assert clip["start_sec"] == 96.5 and clip["end_sec"] == 111.5
    assert clip["original_moment_start"] == 100 and clip["original_moment_end"] == 108
    assert 1 <= clip["quality_score"] <= 10


def test_expansion_shifts_at_video_start(rows):
    rows = [dict(r) for r in rows]
    rows[0]["text"] = GOOD_CLIP["evidence"]
    clip, _ = validate(rows, start_sec=0, end_sec=6)
    assert clip["start_sec"] == 0.0 and clip["duration_sec"] == 15.0


def test_expansion_shifts_at_video_end(rows):
    rows = [dict(r) for r in rows]
    rows[-1]["text"] = GOOD_CLIP["evidence"]
    clip, _ = validate(rows, start_sec=294, end_sec=300)
    assert clip["end_sec"] == 300.0 and clip["duration_sec"] == 15.0


def test_rejections(rows):
    assert v.validate_clip("x", CHUNK, rows, 300, 15, 60)[1] == v.INVALID_STRUCTURE
    assert validate(rows, start_sec="abc")[1] == v.INVALID_TIMESTAMPS
    assert validate(rows, start_sec=110, end_sec=105)[1] == v.INVALID_TIMESTAMPS
    assert validate(rows, start_sec=100, end_sec=101)[1] == v.INVALID_DURATION
    assert validate(rows, start_sec=100, end_sec=190)[1] == v.INVALID_DURATION
    assert validate(rows, start_sec=400, end_sec=410)[1] == v.OUTSIDE_CHUNK
    assert validate(rows, start_sec=295, end_sec=320)[1] == v.INVALID_TIMESTAMPS
    assert validate(rows, evidence="dragons flew over the castle tonight")[1] == v.UNSUPPORTED_EVIDENCE
    assert validate(rows, title="ab")[1] == v.GENERIC_OR_INCOMPLETE
    assert validate(rows, title="Funny gaming moment")[1] == v.GENERIC_OR_INCOMPLETE


def test_score_clamped_and_defaulted(rows):
    assert validate(rows, score=99)[0]["score"] == 10
    assert validate(rows, score="junk")[0]["score"] == 5


def _c(start, end, q, ms=None, me=None):
    return {"start_sec": start, "end_sec": end, "duration_sec": end - start,
            "quality_score": q, "original_moment_start": ms if ms is not None else start,
            "original_moment_end": me if me is not None else end}


def test_dedup_keeps_best_of_overlapping():
    out = remove_duplicate_clips([_c(0, 20, 5), _c(2, 22, 9), _c(100, 120, 4)])
    assert [c["quality_score"] for c in out] == [9, 4]


def test_dedup_close_core_moments_are_duplicates():
    a = _c(0, 15, 8, ms=50, me=58)
    b = _c(200, 215, 7, ms=54, me=64)       # far apart as clips, same core moment
    assert len(remove_duplicate_clips([a, b])) == 1


def test_dedup_empty():
    assert remove_duplicate_clips([]) == []
