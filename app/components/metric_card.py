"""The one metric-card style used across every page.

A number is never alone: it carries a unit and, where it makes sense, a delta
against a baseline, a confidence badge (Observed / Inferred / Missing), an optional
inline sparkline, and a source line for inferred figures.
"""

import streamlit as st

from app.components import icons, theme


def _sparkline_svg(values, w=120, h=26, color=None):
    """Inline SVG polyline from a list of numbers (None gaps skipped). No deps."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return ""
    ys = [v for _, v in pts]
    lo, hi = min(ys), max(ys)
    rng = (hi - lo) or 1.0
    n = len(values)
    coords = " ".join(
        f"{(i / (n - 1)) * w:.1f},{h - (v - lo) / rng * (h - 4) - 2:.1f}" for i, v in pts)
    color = color or theme.ACCENT
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'style="display:block;margin-top:.3rem"><polyline points="{coords}" fill="none" '
            f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def metric_card(label, value, unit=None, delta=None, delta_good_up=True, hint=None,
                tone=None, subtle=False, confidence=None, icon=None, sparkline=None,
                source=None, delta_text=None, delta_direction=None):
    """Render a single metric card.

    delta:           a signed number vs a baseline (auto arrow/colour), or None.
    delta_text:      a ready string chip ("first full period", "+12% vs last"); takes
                     precedence over `delta`. delta_direction: up|down|flat -> colour.
    confidence:      observed|inferred|missing -> O/I/M badge top-right. "missing"
                     omits the value and shows a placeholder instead.
    icon:            Lucide name shown beside the label. sparkline: list[float].
    source:          small provenance line (e.g. "EPRA Nairobi · KES 180/L").
    """
    ic = (icons.icon(icon, size=14, color="var(--ink-faint)") + " ") if icon else ""
    badge = theme.confidence_badge(confidence) if confidence else ""
    header = (f'<div style="display:flex;justify-content:space-between;align-items:center;'
              f'gap:.5rem"><div class="lbl">{ic}{label}</div>{badge}</div>')

    if confidence == "missing":
        placeholder = value if isinstance(value, str) and value else "Pending Genwatt rate confirmation"
        body = (f'<div class="val" style="font-size:1rem;font-weight:600;'
                f'color:var(--ink-faint);margin-top:.5rem">{placeholder}</div>')
    else:
        unit_html = f'<span class="unit">{unit}</span>' if unit else ""
        val_cls = "val alert" if tone == "alert" else "val"
        body = f'<div class="{val_cls}">{value}{unit_html}</div>'

    spark = f'{_sparkline_svg(sparkline)}' if sparkline else ""

    delta_html = ""
    if delta_text:
        delta_html = f'<div class="delta {delta_direction or "flat"}">{delta_text}</div>'
    elif delta is not None:
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "■")
        good = (delta > 0) == delta_good_up
        cls = "flat" if delta == 0 else ("up" if good else "down")
        suffix = f" {hint}" if hint else ""
        delta_html = f'<div class="delta {cls}">{arrow} {abs(delta):g}{suffix}</div>'
    elif hint:
        delta_html = f'<div class="delta flat">{hint}</div>'

    src_html = f'<div class="src">{source}</div>' if source else ""
    card_cls = "tt-card subtle" if subtle else "tt-card"
    st.markdown(f'<div class="{card_cls}">{header}{body}{spark}{delta_html}{src_html}</div>',
                unsafe_allow_html=True)


def cards_row(cards):
    """Lay out a list of metric_card kwargs in responsive columns.

    On a 380px phone Streamlit stacks columns vertically, so this stays usable;
    on desktop they sit side by side.
    """
    cols = st.columns(len(cards))
    for col, kw in zip(cols, cards):
        with col:
            metric_card(**kw)
