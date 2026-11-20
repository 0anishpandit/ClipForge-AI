"""Exception types shared across ClipForge layers.

The UI catches ``ClipForgeError`` for expected, user-facing failures and shows
the message; anything else is an unexpected bug.
"""

from __future__ import annotations


class ClipForgeError(Exception):
    """Base class for expected, user-facing errors."""


class TranscriptError(ClipForgeError):
    """The transcript could not be fetched or parsed."""


class OllamaError(ClipForgeError):
    """The local Ollama server could not be reached or returned bad data."""


class AnalysisError(ClipForgeError):
    """AI analysis finished without any usable clip candidates."""


class RenderError(ClipForgeError):
    """Rendering failed (missing FFmpeg, bad layout, FFmpeg error...)."""

class LiveStreamError(ClipForgeError):
    """Live stream capture or interval shot generation failed."""