"""Visual language for the dashboard: palette, type, chart + map styling.

One warm accent on a quiet neutral palette; system sans only; hierarchy by
size and weight, not colour. Charts carry no in-figure title (the section
header is the title), muted gridlines, tight margins, units in hovers.
"""

import time
from datetime import datetime, timezone

import streamlit as st

import config
from app.components import db

# -- palette ---------------------------------------------------------------
ACCENT = config.ACCENT_COLOR          # burnt orange, used sparingly
ACCENT_RGB = [200, 80, 30]
INK = "#1B1A17"                       # near-black text
MUTED = "#8A857C"                     # secondary text
HAIRLINE = "#E7E3DB"                  # borders / gridlines
PAPER = "#FBFAF7"                     # warm off-white background
CARD = "#FFFFFF"
GOOD = "#3F7D58"
BAD = "#B23A2E"

FONT = ('-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, '
        'Arial, sans-serif')

# Token-free light basemap (Carto Positron) — no Mapbox key required.
MAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

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

  .tt-eyebrow {{ text-transform: uppercase; letter-spacing: .14em;
    font-size: .70rem; font-weight: 700; color: {MUTED}; }}
  .tt-title {{ font-size: 2.0rem; font-weight: 720; margin: .1rem 0 .1rem; }}
  .tt-sub {{ color: {MUTED}; font-size: .95rem; }}

  .tt-card {{ background: {CARD}; border: 1px solid {HAIRLINE};
    border-radius: 14px; padding: 1.0rem 1.1rem; height: 100%; }}
  .tt-card .lbl {{ text-transform: uppercase; letter-spacing: .08em;
    font-size: .68rem; font-weight: 700; color: {MUTED}; }}
  .tt-card .val {{ font-size: 1.85rem; font-weight: 720; line-height: 1.05;
    margin-top: .35rem; }}
  .tt-card .val .unit {{ font-size: .9rem; font-weight: 600; color: {MUTED};
    margin-left: .25rem; }}
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
  .tt-pill.high {{ background:#F6E1DD; color:{BAD}; }}
  .tt-pill.medium {{ background:#F6ECD9; color:#9A6B16; }}
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


PERIODS = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All data": None}


def period_selector():
    """Sidebar period control, anchored to the latest data we hold.

    Returns (from_ts, to_ts, label). Persists across pages via session state.
    """
    st.sidebar.markdown("**Period**")
    label = st.sidebar.selectbox("Period", list(PERIODS), index=1,
                                 label_visibility="collapsed", key="tt_period")
    days = PERIODS[label]
    to_ts = db.last_data_ts() or int(time.time())
    from_ts = 0 if days is None else to_ts - days * 86400
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
