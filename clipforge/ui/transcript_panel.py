"""Transcript table, metrics and download button."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from clipforge.transcript.formatting import to_plain_text
from clipforge.utils import fmt_time


def render_transcript(rows: list[dict]) -> None:
    if not rows:
        return

    st.subheader("📝 Transcript")
    left, right = st.columns(2)
    left.metric("Transcript segments", len(rows))
    right.metric("Video duration", fmt_time(max(row["end_sec"] for row in rows)))

    st.dataframe(
        pd.DataFrame(rows)[["timestamp", "text"]],
        width="stretch", hide_index=True, height=320,
    )
    st.download_button(
        "Download transcript (.txt)",
        data=to_plain_text(rows).encode("utf-8"),
        file_name="clipforge_transcript.txt",
        mime="text/plain",
        on_click="ignore",
    )
