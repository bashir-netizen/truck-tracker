"""The one metric-card style used across every page.

A number is never alone: it carries a unit and, where it makes sense, a
delta against a baseline (previous period or rolling average).
"""

import streamlit as st

from app.components import theme


def metric_card(label, value, unit=None, delta=None, delta_good_up=True, hint=None,
                tone=None, subtle=False):
    """Render a single metric card.

    delta: a signed number (already computed vs a baseline) or None.
    delta_good_up: whether an increase is good (drives the colour).
    tone: "alert" renders the value in the alert colour (e.g. hard-safety > 0).
    subtle: a lighter, supplementary card (e.g. a reference figure).
    """
    unit_html = f'<span class="unit">{unit}</span>' if unit else ""
    delta_html = ""
    if delta is not None:
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "■")
        good = (delta > 0) == delta_good_up
        cls = "flat" if delta == 0 else ("up" if good else "down")
        suffix = f" {hint}" if hint else ""
        delta_html = f'<div class="delta {cls}">{arrow} {abs(delta):g}{suffix}</div>'
    elif hint:
        delta_html = f'<div class="delta flat">{hint}</div>'

    card_cls = "tt-card subtle" if subtle else "tt-card"
    val_cls = "val alert" if tone == "alert" else "val"
    st.markdown(
        f'<div class="{card_cls}"><div class="lbl">{label}</div>'
        f'<div class="{val_cls}">{value}{unit_html}</div>{delta_html}</div>',
        unsafe_allow_html=True,
    )


def cards_row(cards):
    """Lay out a list of metric_card kwargs in responsive columns.

    On a 380px phone Streamlit stacks columns vertically, so this stays
    usable; on desktop they sit side by side.
    """
    cols = st.columns(len(cards))
    for col, kw in zip(cols, cards):
        with col:
            metric_card(**kw)
