import sys
from pathlib import Path

import pytest

# Make ``import clipforge`` work no matter where pytest is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_rows(total_seconds=300, step=5, special=None):
    """Transcript rows every ``step`` seconds; ``special`` maps start_sec -> text."""
    special = special or {}
    rows = []
    for start in range(0, total_seconds, step):
        rows.append({
            "start_sec": float(start),
            "end_sec": float(start + step),
            "timestamp": f"{start // 60:02d}:{start % 60:02d}",
            "text": special.get(start, f"ordinary filler dialogue number {start}"),
        })
    return rows


@pytest.fixture
def rows():
    return make_rows(special={
        100: "oh my god the boss just exploded",
        105: "that was completely unexpected honestly",
    })


class FakeClient:
    """Stands in for OllamaClient: returns canned replies (or raises) in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat_json(self, system_prompt, user_prompt):
        self.calls += 1
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


GOOD_CLIP = {
    "start_sec": 100, "end_sec": 108,
    "title": "Boss explodes without warning",
    "hook": "Nobody saw this coming",
    "reason": "Genuine surprise reaction from the streamer",
    "evidence": "oh my god the boss just exploded",
    "score": 8,
}
