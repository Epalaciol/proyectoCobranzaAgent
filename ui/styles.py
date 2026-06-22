import os
import streamlit as st


def _load(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "static", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def inject_css() -> None:
    """Lee static/styles.css y lo inyecta en la página de Streamlit."""
    css = _load("styles.css")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
