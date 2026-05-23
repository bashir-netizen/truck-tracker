"""The colored band under the header: overall status at a glance.

Green when nothing's flagged, amber for a few items, red when any item is
critical (a hard-safety event or a high-severity anomaly).
"""

import streamlit as st


def render(items):
    """items: the list from status_panel.gather(). Drives colour + wording."""
    critical = any(i["severity"] == "critical" for i in items)
    if critical:
        bg, text = "var(--critical)", "Action required"
    elif items:
        bg, text = "var(--warn)", f"{len(items)} item{'s' if len(items) != 1 else ''} need attention"
    else:
        bg, text = "var(--ok)", "All clear"
    st.markdown(
        f'<div style="background:{bg};color:#fff;border-radius:8px;padding:.5rem .9rem;'
        f'font-weight:600;font-size:var(--t-small);display:flex;justify-content:space-between;'
        f'align-items:center;margin:.2rem 0 .4rem"><span>{text}</span>'
        f'<span style="opacity:.85">&#8595; status below</span></div>',
        unsafe_allow_html=True)
