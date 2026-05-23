"""One round-trip group on the Overview — 'Marsabit run · long-haul · 1 trip'."""

import streamlit as st

from app.components import theme


def render(title, class_label, count, context, when_str, km, dur_str="", multi=False):
    badge = theme.confidence_badge("inferred")
    when = f"latest {when_str}" if multi else when_str
    stats = (f"{when} · ~{km:,.0f} km round trip"
             + (f" · ~{dur_str}{' each' if multi else ''}" if dur_str else ""))
    st.markdown(
        '<div style="padding:.5rem 0;border-bottom:1px solid var(--border)">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:.5rem">'
        f'<div><b>{title}</b> <span class="tt-pill neutral">{class_label}</span> '
        f'<span class="tt-small">· {count} trip{"s" if count != 1 else ""}</span></div>{badge}</div>'
        + (f'<div class="tt-small">{context}</div>' if context else '')
        + f'<div class="tt-small">{stats}</div></div>',
        unsafe_allow_html=True)
