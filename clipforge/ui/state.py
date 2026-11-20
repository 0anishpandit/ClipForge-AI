"""Streamlit session-state keys and helpers."""

from __future__ import annotations

import streamlit as st

_DEFAULTS = {
    "transcript_rows": list,
    "clips": list,
    "video_id": lambda: None,
    "clips_version": lambda: 0,    # bumps on every new analysis -> resets the table editor
    "render_archive": lambda: None,  # ZIP bytes of the last render
}


def init_state() -> None:
    for key, factory in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = factory()


def set_transcript(video_id: str, rows: list[dict]) -> None:
    st.session_state.transcript_rows = rows
    st.session_state.video_id = video_id
    set_clips([])


def set_clips(clips: list[dict]) -> None:
    st.session_state.clips = clips
    st.session_state.clips_version += 1
    st.session_state.render_archive = None
