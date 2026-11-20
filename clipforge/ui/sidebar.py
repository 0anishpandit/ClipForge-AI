"""Sidebar: caption language, clip limits and local-AI settings."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from clipforge.ai.ollama import OllamaClient
from clipforge.config import Settings


@dataclass(frozen=True)
class SidebarSettings:
    language: str
    clip_count: int
    min_duration: int
    max_duration: int
    model: str


def render_sidebar(settings: Settings) -> SidebarSettings:
    with st.sidebar:
        st.header("⚙️ Settings")

        language = st.selectbox("Caption language", ["en", "en-US", "en-GB"], index=0)
        clip_count = st.slider("Maximum clip suggestions", 1, 20, 10)
        min_duration = st.slider("Minimum clip length (seconds)", 10, 30, 15)
        max_duration = st.slider("Maximum clip length (seconds)", 30, 90, 60)

        st.divider()
        st.subheader("🧠 Local AI Settings")
        model = st.text_input("Ollama model", value=settings.ollama_model)

        if st.button("Check local AI connection"):
            client = OllamaClient(settings.ollama_url, model)
            available = client.list_models()
            if available is None:
                st.error(f"Ollama is not running or cannot be reached at {settings.ollama_url}.")
            else:
                st.success("Ollama is running.")
                if model in available:
                    st.success(f"{model} is installed.")
                else:
                    st.warning(f"{model} was not found. Check the output of `ollama list`.")

        st.caption("ClipForge uses local Ollama AI. No OpenAI API key or paid API is required.")

    return SidebarSettings(language, clip_count, min_duration, max_duration, model)
