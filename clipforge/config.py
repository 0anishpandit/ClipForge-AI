"""Central configuration.

Defaults live here. Every value that a user may reasonably want to change can
be overridden with an environment variable (or a ``.env`` file in the project
root) prefixed with ``CLIPFORGE_``. No machine-specific paths are stored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Transcript chunking defaults (shared by transcript.chunking).
DEFAULT_MAX_CHUNK_CHARS = 4500
DEFAULT_CHUNK_OVERLAP_SECONDS = 60
# How far (seconds) an AI timestamp may stray outside its chunk / the video.
DEFAULT_TIMESTAMP_TOLERANCE = 3.0

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ``.

    Existing environment variables always win. Blank lines and ``#`` comment
    lines are ignored; surrounding quotes on values are removed.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"\'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings."""

    ollama_url: str = DEFAULT_OLLAMA_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout: int = 600
    ollama_num_ctx: int = 8192
    max_generation_tokens: int = 700
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS
    chunk_overlap_seconds: int = DEFAULT_CHUNK_OVERLAP_SECONDS
    timestamp_tolerance: float = DEFAULT_TIMESTAMP_TOLERANCE
    ffmpeg_path: str = ""  # empty -> look up "ffmpeg" on PATH
    log_level: str = "INFO"
    facecam_sample_frames: int = 12
    facecam_min_confidence: float = 0.25

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ollama_url=_env_str("CLIPFORGE_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/"),
            ollama_model=_env_str("CLIPFORGE_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            ollama_timeout=_env_int("CLIPFORGE_OLLAMA_TIMEOUT", 600),
            ollama_num_ctx=_env_int("CLIPFORGE_OLLAMA_NUM_CTX", 8192),
            max_generation_tokens=_env_int("CLIPFORGE_MAX_GENERATION_TOKENS", 700),
            ffmpeg_path=_env_str("CLIPFORGE_FFMPEG", ""),
            log_level=_env_str("CLIPFORGE_LOG_LEVEL", "INFO").upper(),
            facecam_sample_frames=_env_int("CLIPFORGE_FACECAM_SAMPLE_FRAMES", 12),
            facecam_min_confidence=_env_float("CLIPFORGE_FACECAM_MIN_CONFIDENCE", 0.25),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings (reads ``.env`` once)."""
    load_env_file()
    return Settings.from_env()
