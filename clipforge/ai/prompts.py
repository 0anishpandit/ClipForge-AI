"""Prompt templates for highlight detection."""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a professional short-form gaming video editor. "
    "Analyze timestamped gaming transcripts and identify moments "
    "that could work as engaging YouTube Shorts, TikToks or Reels. "
    "Only identify moments supported by the transcript. Return JSON only."
)

RETRY_SYSTEM_PROMPT = (
    "You are an expert gaming video editor. "
    "Identify genuinely interesting moments supported by the transcript. "
    "Return valid JSON only."
)


def build_system_prompt(retry: bool = False) -> str:
    return RETRY_SYSTEM_PROMPT if retry else SYSTEM_PROMPT


def build_user_prompt(
    transcript_text: str, clip_count: int, min_duration: float, max_duration: float
) -> str:
    return f"""
Find up to {clip_count} strong short-form gaming highlights.

Look for funny moments, unexpected reactions, surprising discoveries,
exciting or dramatic moments, interesting conversations, unusual gameplay
events described in dialogue, and strong hooks.

Timestamp rules:
- Use the exact transcript timeline.
- Do not invent timestamps.
- Identify the core interesting moment, not unnecessary surrounding dialogue.
- The final clip will be expanded to fit the requested duration.
- Core moments may be shorter than {min_duration} seconds.
- Never exceed {max_duration} seconds for the core moment.

Quality rules:
- Avoid ordinary conversations without a clear highlight.
- Avoid generic titles.
- Give specific reasons.
- Evidence must contain actual words from the supplied transcript.
- Score each candidate from 1 to 10.

Return valid JSON in this structure:
{{
  "clips": [
    {{
      "start_sec": 120.5,
      "end_sec": 128.5,
      "title": "Specific and engaging title",
      "hook": "A short hook for viewers",
      "reason": "Why this moment deserves to be a clip",
      "evidence": "Words actually spoken in the transcript",
      "score": 8
    }}
  ]
}}

If no strong moments exist, return {{"clips": []}}.

TRANSCRIPT:
{transcript_text}
"""
