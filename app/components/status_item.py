"""A single status row: severity icon, title, evidence, confidence badge, View link."""

import streamlit as st

from app.components import icons, theme

_SEV_COLOR = {"critical": "var(--critical)", "warn": "var(--warn)", "info": "var(--ink-muted)"}
_SEV_ICON = {"critical": "alert-circle", "warn": "alert-circle", "info": "circle-help"}


def render(item):
    """item: {severity, title, evidence, page, confidence}. Renders one row."""
    c1, c2 = st.columns([6, 1])
    with c1:
        color = _SEV_COLOR.get(item["severity"], "var(--ink-muted)")
        ic = icons.icon(_SEV_ICON.get(item["severity"], "alert-circle"), 16, color)
        badge = theme.confidence_badge(item.get("confidence"))
        st.markdown(
            f'<div style="display:flex;gap:.55rem;align-items:flex-start">'
            f'<span style="margin-top:1px">{ic}</span>'
            f'<div><div style="font-weight:600;color:var(--ink)">{item["title"]} {badge}</div>'
            f'<div class="tt-small">{item["evidence"]}</div></div></div>',
            unsafe_allow_html=True)
    with c2:
        if item.get("page"):
            st.page_link(item["page"], label="View →")
