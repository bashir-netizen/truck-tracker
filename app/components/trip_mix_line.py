"""The inline trip-mix sentence: '4 long-haul · 3 regional · 4 local · 2 yard'."""

import streamlit as st

_ORDER = [("long_haul", "long-haul"), ("regional", "regional"),
          ("local", "local"), ("yard", "yard")]


def render(counts):
    """counts: {journey_character: n}. Renders only the classes that occurred."""
    parts = [f"<b>{int(counts.get(c, 0))}</b> {label}" for c, label in _ORDER if counts.get(c, 0)]
    st.markdown(f'<div class="tt-mix">{" · ".join(parts) if parts else "No trips this period."}</div>',
                unsafe_allow_html=True)
