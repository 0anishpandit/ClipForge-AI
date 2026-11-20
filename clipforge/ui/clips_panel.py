"""Editable table of suggested clips."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

_READ_ONLY_COLUMNS = [
    "start", "end", "duration_sec", "hook", "reason", "evidence", "score",
    "evidence_match", "quality_score", "original_moment_start", "original_moment_end",
]


def render_clip_editor(clips: list[dict], version: int) -> list[dict]:
    """Show the clips and return the (possibly user-edited) rows."""
    st.subheader("🎯 Suggested clips")
    st.caption(
        "Candidates are ranked by AI-assigned scores. "
        "Review the evidence and timestamps before rendering."
    )

    edited = st.data_editor(
        pd.DataFrame(clips),
        width="stretch",
        hide_index=True,
        column_config={
            "start_sec": st.column_config.NumberColumn("Start (sec)", format="%.2f"),
            "end_sec": st.column_config.NumberColumn("End (sec)", format="%.2f"),
            "duration_sec": st.column_config.NumberColumn("Duration (sec)", format="%.1f"),
            "score": st.column_config.NumberColumn("AI score", format="%.1f"),
        },
        disabled=_READ_ONLY_COLUMNS,
        # A new key per analysis stops edits from a previous run leaking in.
        key=f"clip_editor_{version}",
    )
    records = edited.to_dict(orient="records")

    st.download_button(
        "Download clip plan (.json)",
        data=json.dumps(records, indent=2).encode("utf-8"),
        file_name="clipforge_clip_plan.json",
        mime="application/json",
        on_click="ignore",
    )
    return records
