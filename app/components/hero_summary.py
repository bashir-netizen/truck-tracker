"""The full-width hero panel: the period's story as labelled, badged bullets."""

import streamlit as st

from app.components import icons, theme


def render(title, bullets):
    """bullets: list of {icon, label, value, sub, confidence, delta_text, delta_direction}."""
    rows = ""
    for b in bullets:
        ic = icons.icon(b.get("icon", ""), 16, "var(--ink-faint)") if b.get("icon") else ""
        badge = theme.confidence_badge(b.get("confidence")) if b.get("confidence") else ""
        delta = ""
        if b.get("delta_text"):
            delta = (f'<span class="delta {b.get("delta_direction", "flat")}" '
                     f'style="margin-left:.4rem">{b["delta_text"]}</span>')
        sub = f'<span class="tt-small" style="margin-left:.4rem">{b["sub"]}</span>' if b.get("sub") else ""
        rows += (
            '<div style="display:flex;align-items:baseline;gap:.5rem;padding:.4rem 0;'
            'border-bottom:1px solid var(--border)">'
            f'<span style="width:18px;flex:none">{ic}</span>'
            f'<span class="tt-small" style="width:108px;flex:none;color:var(--ink-muted)">{b["label"]}</span>'
            f'<b style="font-variant-numeric:tabular-nums">{b["value"]}</b>{sub}{delta}'
            f'<span style="margin-left:auto">{badge}</span></div>')
    st.markdown(
        f'<div class="tt-card"><div class="lbl" style="margin-bottom:.3rem">{title}</div>{rows}</div>',
        unsafe_allow_html=True)
