"""Visual language for the dashboard: palette, type, chart + map styling.

One warm accent on a quiet neutral palette; system sans only; hierarchy by
size and weight, not colour. Charts carry no in-figure title (the section
header is the title), muted gridlines, tight margins, units in hovers.
"""

import time
from datetime import date, datetime, timedelta, timezone

import streamlit as st

import config
from app.components import db

# -- palette ---------------------------------------------------------------
ACCENT = config.ACCENT_COLOR          # burnt orange, used sparingly
ACCENT_RGB = [31, 111, 235]           # primary blue
CORRIDOR_RGB = [71, 85, 105]          # neutral slate for route lines
PLACE_RGB = [30, 41, 59]              # slate-dark place bubbles (labelled on map)

# Journey character labels + colours (one palette for filter, strip, headline).
CLASS_LABELS = {"long_haul": "long haul", "regional": "regional",
                "local": "local", "yard": "yard"}
TRIP_CLASS_COLORS = {"long_haul": "#1F6FEB", "regional": "#D97706", "local": "#16A34A"}
CLASS_COLORS = {**TRIP_CLASS_COLORS, "yard": "#94A3B8"}

# Per-trip track width by class (long-haul dominant). Used by the Map PathLayer.
CLASS_WIDTH = {"long_haul": 8, "regional": 5, "local": 3, "yard": 2}

# 8-colour accessible categorical palette for per-trip tracks, assigned by date.
TRIP_DATE_PALETTE = ["#c43d2f", "#1d6fb8", "#1d8a4a", "#c47d1d",
                     "#7b4fb0", "#0f8e8e", "#b03f7a", "#5b6770"]


def date_colors(ordered_days):
    """Map dates -> palette colours by sequential position (not a hash).

    `ordered_days` = the dates currently shown, newest-first. Position i gets
    TRIP_DATE_PALETTE[i % 8], so adjacent dates never share a colour (collisions
    only at distance >= 8). TRADEOFF: colours are NOT stable across date-range
    changes — switching 7d<->30d can recolour a given date. That's intentional:
    it buys readable, collision-free adjacent colours within any one view, which a
    hash can't guarantee (the old hash put adjacent May 17/18 on the same green).
    """
    return {d: TRIP_DATE_PALETTE[i % len(TRIP_DATE_PALETTE)]
            for i, d in enumerate(ordered_days)}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
INK = "#0F172A"                       # slate ink (body text)
MUTED = "#64748B"                     # secondary text
HAIRLINE = "#E5E7EB"                  # borders / gridlines
PAPER = "#F7F8FA"                     # cool near-white background
CARD = "#FFFFFF"
GOOD = "#16A34A"
BAD = "#DC2626"

FONT = ('-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, '
        'Arial, sans-serif')

# Token-free light basemap (Carto Positron) — no Mapbox key required.
MAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

# Canonical wording for the Wialon eco score — reuse everywhere the score appears
# (Driver card, Overview Care card) so the phrasing can never drift.
WIALON_SCORE_NOTE = (
    "Computed using Wialon's documented penalty→rank formula with this unit's "
    "configured penalty points. Cross-checkable against Wialon's Eco Driving tab. "
    "The remote report API does not expose this value, so we reproduce it locally."
)

_CSS = f"""
<style>
  :root {{ --accent: {ACCENT}; --ink: {INK}; --muted: {MUTED};
           --hair: {HAIRLINE}; --paper: {PAPER}; }}
  html, body, [class*="css"], .stApp {{ font-family: {FONT}; color: {INK}; }}
  .stApp {{ background: {PAPER}; }}
  #MainMenu, footer {{ visibility: hidden; }}
  .block-container {{ padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1100px; }}
  h1, h2, h3 {{ letter-spacing: -0.02em; font-weight: 680; }}
  a {{ color: {ACCENT}; }}
  /* widget labels must read as dark body text (belt-and-suspenders with config.toml) */
  [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p {{
    color: {INK} !important; font-weight: 600; }}

  .tt-strip {{ border-top: 1px solid {HAIRLINE}; border-bottom: 1px solid {HAIRLINE};
    padding: .55rem 0 .15rem; margin: .4rem 0 1rem; }}
  .tt-legend {{ display: flex; gap: 1.2rem; font-size: .8rem; color: {INK};
    font-weight: 600; margin-bottom: .15rem; }}
  .tt-legend .dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 999px;
    margin-right: .4rem; vertical-align: middle; }}
  .tt-mix {{ font-size: 1.0rem; color: {INK}; margin: .2rem 0 .6rem; }}

  .tt-eyebrow {{ text-transform: uppercase; letter-spacing: .14em;
    font-size: .70rem; font-weight: 700; color: {MUTED}; }}
  .tt-title {{ font-size: 2.0rem; font-weight: 720; margin: .1rem 0 .1rem; }}
  .tt-sub {{ color: {MUTED}; font-size: .95rem; }}

  .tt-card {{ background: {CARD}; border: 1px solid {HAIRLINE};
    border-radius: 14px; padding: 1.0rem 1.1rem; height: 100%;
    box-shadow: 0 1px 2px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.04); }}
  .tt-card .lbl {{ text-transform: uppercase; letter-spacing: .08em;
    font-size: .68rem; font-weight: 700; color: {MUTED}; }}
  .tt-card .val {{ font-size: 1.85rem; font-weight: 720; line-height: 1.05;
    margin-top: .35rem; }}
  .tt-card .val .unit {{ font-size: .9rem; font-weight: 600; color: {MUTED};
    margin-left: .25rem; }}
  .tt-card .val.alert {{ color: {BAD}; }}
  .tt-card.subtle {{ background: transparent; border-style: dashed;
    box-shadow: none; }}
  .tt-card.subtle .lbl {{ color: {MUTED}; }}
  .tt-card.subtle .val {{ font-size: 1.3rem; color: {MUTED}; font-weight: 650; }}
  .tt-card .delta {{ font-size: .8rem; font-weight: 600; margin-top: .4rem; }}
  .tt-card .delta.up {{ color: {GOOD}; }} .tt-card .delta.down {{ color: {BAD}; }}
  .tt-card .delta.flat {{ color: {MUTED}; }}

  .tt-empty {{ border: 1px dashed {HAIRLINE}; border-radius: 14px;
    padding: 1.6rem; text-align: center; color: {MUTED}; background: {CARD}; }}
  .tt-empty .t {{ color: {INK}; font-weight: 650; margin-bottom: .25rem; }}

  .tt-row {{ display:flex; justify-content:space-between; align-items:center;
    padding:.6rem 0; border-bottom:1px solid {HAIRLINE}; }}
  .tt-pill {{ display:inline-block; padding:.08rem .5rem; border-radius:999px;
    font-size:.72rem; font-weight:700; }}
  .tt-pill.high {{ background:#FEE2E2; color:{BAD}; }}
  .tt-pill.medium {{ background:#FEF3C7; color:#B45309; }}
  hr {{ border:none; border-top:1px solid {HAIRLINE}; margin:1.2rem 0; }}
</style>
"""


def page_setup(title):
    """First call on every page: configure, inject CSS. Returns nothing."""
    st.set_page_config(page_title=f"{title} · Truck Tracker", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(_CSS, unsafe_allow_html=True)


def header(title, subtitle=None):
    st.markdown(f'<div class="tt-eyebrow">{config.UNIT_DISPLAY_NAME} · '
                f'{config.UNIT_DESCRIPTION}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="tt-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="tt-sub">{subtitle}</div>', unsafe_allow_html=True)
    st.markdown('<hr/>', unsafe_allow_html=True)


def style_fig(fig, height=300):
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8),
        font=dict(family=FONT, color=INK, size=13),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, hoverlabel=dict(font_family=FONT),
        xaxis=dict(gridcolor=HAIRLINE, zeroline=False),
        yaxis=dict(gridcolor=HAIRLINE, zeroline=False),
    )
    return fig


def fmt_dt(ts, with_time=True):
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(int(ts), timezone.utc)
    return dt.strftime("%d %b %Y, %H:%M") if with_time else dt.strftime("%d %b %Y")


def fmt_dur(seconds):
    """Human duration: '3d 4h', '5h 12m', '23m'."""
    if seconds is None:
        return "—"
    s = int(seconds)
    h, m = s // 3600, (s % 3600) // 60
    if h >= 24:
        return f"{h // 24}d {h % 24}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


# Preset name -> length in seconds (None = all history).
PERIODS = {
    "Last 24 hours": 86400,
    "Last 3 days": 3 * 86400,
    "Last 7 days": 7 * 86400,
    "Last 30 days": 30 * 86400,
    "All data": None,
    "Custom range…": "custom",
}
_DEFAULT = "Last 30 days"


def _day_start(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def period_selector():
    """Sidebar period control, anchored to the latest data we hold.

    Presets plus a custom from–to range (for matching a billing period).
    Returns (from_ts, to_ts, label) and shows the resolved range in the sidebar.
    """
    st.sidebar.markdown("**Period**")
    choice = st.sidebar.selectbox("Period", list(PERIODS),
                                  index=list(PERIODS).index(_DEFAULT),
                                  label_visibility="collapsed", key="tt_period")
    anchor = db.last_data_ts() or int(time.time())
    span = PERIODS[choice]

    if span == "custom":
        d_to = datetime.fromtimestamp(anchor, timezone.utc).date()
        d_from = (datetime.fromtimestamp(anchor, timezone.utc) - timedelta(days=30)).date()
        c1, c2 = st.sidebar.columns(2)
        d_from = c1.date_input("From", value=d_from, key="tt_from")
        d_to = c2.date_input("To", value=d_to, key="tt_to")
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        from_ts, to_ts = _day_start(d_from), _day_start(d_to) + 86399
        label = f"{d_from:%d %b} – {d_to:%d %b %Y}"
    elif span is None:
        from_ts, to_ts, label = 0, anchor, "All data"
    else:
        from_ts, to_ts, label = anchor - span, anchor, choice

    st.sidebar.caption(f"Showing {fmt_dt(from_ts, with_time=False)} – "
                       f"{fmt_dt(to_ts, with_time=False)}")
    return from_ts, to_ts, label


def freshness_caption():
    last = db.last_data_ts()
    ingested = db.last_ingest_ts()
    bits = []
    if last:
        bits.append(f"Data as of {fmt_dt(last)} UTC")
    if ingested:
        bits.append(f"last ingestion {fmt_dt(ingested)} UTC")
    if bits:
        st.sidebar.caption(" · ".join(bits))
