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
ACCENT = config.ACCENT_COLOR          # Kenyan red — the one accent colour
ACCENT_RGB = [196, 61, 47]            # = #c43d2f
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


# Design-system tokens — warm paper, one red accent; hierarchy by size/weight.
INK = "#0e1116"          # near-black body text
INK_MUTED = "#4a5260"    # secondary text
INK_FAINT = "#8a92a3"    # tertiary text / labels
MUTED = INK_MUTED        # back-compat alias (older pages import theme.MUTED)
PAPER = "#f7f4ef"        # warm off-white app background
SURFACE = "#ffffff"      # cards
SURFACE_ALT = "#f0ebe2"  # warm inset / zebra
CARD = SURFACE           # back-compat alias
BORDER = "#e6e8ec"
HAIRLINE = BORDER        # back-compat alias
STATUS_OK = "#1d8a4a"
STATUS_WARN = "#c47d1d"
STATUS_CRITICAL = "#c43d2f"
GOOD = STATUS_OK         # back-compat alias
BAD = STATUS_CRITICAL    # back-compat alias
SHADOW_SM = "0 1px 2px rgba(14,17,22,0.04)"
SHADOW_MD = "0 1px 2px rgba(14,17,22,0.04), 0 4px 16px rgba(14,17,22,0.04)"

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
  :root {{
    --bg: {PAPER}; --surface: {SURFACE}; --surface-alt: {SURFACE_ALT};
    --ink: {INK}; --ink-muted: {INK_MUTED}; --ink-faint: {INK_FAINT};
    --accent: {ACCENT}; --border: {BORDER};
    --ok: {STATUS_OK}; --warn: {STATUS_WARN}; --critical: {STATUS_CRITICAL};
    --shadow-sm: {SHADOW_SM}; --shadow-md: {SHADOW_MD};
    --r-card: 12px; --r-btn: 8px; --r-pill: 999px;
    --t-h1: 36px; --t-h2: 24px; --t-h3: 18px;
    --t-body: 15px; --t-small: 13px; --t-micro: 11px;
  }}
  html, body, [class*="css"], .stApp {{ font-family: {FONT}; color: var(--ink);
    font-size: var(--t-body); }}
  .stApp {{ background: var(--bg); }}
  #MainMenu, footer {{ visibility: hidden; }}
  .block-container {{ padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1100px; }}
  /* tabular numerals wherever figures matter */
  .tt-card .val, .tt-num, [data-testid="stMetricValue"] {{
    font-variant-numeric: tabular-nums; }}

  /* type scale */
  h1, .tt-h1 {{ font-size: var(--t-h1); font-weight: 700; letter-spacing: -0.02em;
    line-height: 1.1; }}
  h2, .tt-h2 {{ font-size: var(--t-h2); font-weight: 600; letter-spacing: -0.01em;
    line-height: 1.2; }}
  h3, .tt-h3 {{ font-size: var(--t-h3); font-weight: 600; line-height: 1.3; }}
  .tt-body {{ font-size: var(--t-body); font-weight: 400; }}
  .tt-small {{ font-size: var(--t-small); font-weight: 400; color: var(--ink-muted); }}
  .tt-micro {{ font-size: var(--t-micro); font-weight: 500; letter-spacing: .04em; }}
  a {{ color: var(--accent); }}
  [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p {{
    color: var(--ink) !important; font-weight: 600; }}

  /* header bits */
  .tt-eyebrow {{ text-transform: uppercase; letter-spacing: .14em;
    font-size: var(--t-micro); font-weight: 700; color: var(--ink-faint); }}
  .tt-title {{ font-size: var(--t-h1); font-weight: 700; letter-spacing: -0.02em;
    line-height: 1.1; margin: .1rem 0; }}
  .tt-sub {{ color: var(--ink-muted); font-size: var(--t-body); }}
  .tt-mix {{ font-size: var(--t-body); color: var(--ink); margin: .2rem 0 .6rem; }}

  /* cards */
  .tt-card {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--r-card); padding: 1.0rem 1.1rem; height: 100%;
    box-shadow: var(--shadow-sm); }}
  .tt-card .lbl {{ text-transform: uppercase; letter-spacing: .08em;
    font-size: var(--t-micro); font-weight: 700; color: var(--ink-muted); }}
  .tt-card .val {{ font-size: 34px; font-weight: 700; line-height: 1.05;
    margin-top: .35rem; }}
  .tt-card .val .unit {{ font-size: var(--t-small); font-weight: 600;
    color: var(--ink-muted); margin-left: .25rem; }}
  .tt-card .val.alert {{ color: var(--critical); }}
  .tt-card.subtle {{ background: transparent; border-style: dashed; box-shadow: none; }}
  .tt-card.subtle .lbl {{ color: var(--ink-muted); }}
  .tt-card.subtle .val {{ font-size: 22px; color: var(--ink-muted); font-weight: 650; }}
  .tt-card .delta {{ font-size: var(--t-small); font-weight: 600; margin-top: .4rem; }}
  .tt-card .delta.up {{ color: var(--ok); }} .tt-card .delta.down {{ color: var(--critical); }}
  .tt-card .delta.flat {{ color: var(--ink-muted); }}
  .tt-card .src {{ font-size: var(--t-micro); color: var(--ink-faint); margin-top: .35rem; }}

  /* confidence badge (O / I / M) */
  .tt-conf {{ display:inline-flex; align-items:center; justify-content:center;
    width:16px; height:16px; border-radius:999px; font-size:10px; font-weight:700;
    border:1px solid currentColor; cursor:default; vertical-align:middle; }}
  .tt-conf.observed {{ color: var(--ok); }}
  .tt-conf.inferred {{ color: var(--ink-muted); }}
  .tt-conf.missing {{ color: var(--ink-faint); }}

  /* pills */
  .tt-pill {{ display:inline-block; padding:.08rem .5rem; border-radius:var(--r-pill);
    font-size:var(--t-micro); font-weight:700; }}
  .tt-pill.accent {{ background: var(--accent); color:#fff; }}
  .tt-pill.neutral {{ background: var(--surface-alt); color: var(--ink-muted);
    border:1px solid var(--border); }}
  .tt-pill.high {{ background:#fbe3df; color:var(--critical); }}
  .tt-pill.medium {{ background:#f6ecd6; color:#9a5b14; }}

  /* strip / legend / empty / row */
  .tt-strip {{ border-top:1px solid var(--border); border-bottom:1px solid var(--border);
    padding:.55rem 0 .15rem; margin:.4rem 0 1rem; }}
  .tt-legend {{ display:flex; gap:1.2rem; flex-wrap:wrap; font-size:var(--t-small);
    color:var(--ink); font-weight:600; margin-bottom:.15rem; }}
  .tt-legend .dot {{ display:inline-block; width:9px; height:9px; border-radius:999px;
    margin-right:.4rem; vertical-align:middle; }}
  .tt-empty {{ border:1px dashed var(--border); border-radius:var(--r-card);
    padding:1.6rem; text-align:center; color:var(--ink-muted); background:var(--surface); }}
  .tt-empty .t {{ color:var(--ink); font-weight:650; margin-bottom:.25rem; }}
  .tt-row {{ display:flex; justify-content:space-between; align-items:center;
    padding:.6rem 0; border-bottom:1px solid var(--border); }}
  hr {{ border:none; border-top:1px solid var(--border); margin:1.2rem 0; }}

  /* sidebar: hide Streamlit's default page nav (we render our own) */
  [data-testid="stSidebarNav"] {{ display: none; }}
  .tt-navtitle {{ font-weight:700; font-size:var(--t-small); letter-spacing:.02em;
    color:var(--ink); padding:.1rem .2rem .5rem; }}

  /* print: a clean one-page audit document (hide chrome + interactive controls) */
  @media print {{
    [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"],
    .stButton, [data-testid="stToggle"], [data-testid="stSlider"],
    [data-testid="stSelectbox"], [data-testid="stSegmentedControl"],
    [data-testid="stDateInput"], [data-testid="stExpander"], iframe {{ display:none !important; }}
    .stApp {{ background:#fff !important; }}
    .block-container {{ max-width:100% !important; padding-top:0 !important; }}
    .tt-card {{ box-shadow:none !important; break-inside:avoid; }}
  }}

  /* mobile: comfortable single column at phone widths */
  @media (max-width: 640px) {{
    .block-container {{ padding-left:1rem; padding-right:1rem; }}
    .tt-title {{ font-size:28px; }}
    .tt-card .val {{ font-size:28px; }}
  }}
</style>
"""


# -- confidence categories (Observed / Inferred / Missing) -----------------
CONFIDENCE = {
    "observed": {"label": "Observed", "letter": "O", "icon": "circle-check",
                 "tooltip": "Measured directly by the tracker."},
    "inferred": {"label": "Inferred", "letter": "I", "icon": "function-square",
                 "tooltip": "Computed from tracker data with assumptions."},
    "missing": {"label": "Missing", "letter": "M", "icon": "circle-help",
                "tooltip": "Needs external data we don't have yet."},
}


def confidence_badge(kind):
    """Small O/I/M pill (colour by category) with a hover tooltip. HTML string."""
    c = CONFIDENCE.get(kind)
    if not c:
        return ""
    return (f'<span class="tt-conf {kind}" title="{c["label"]}: {c["tooltip"]}">'
            f'{c["letter"]}</span>')


_NAV = [("main.py", "Overview", "home"), ("pages/1_Map.py", "Map", "map"),
        ("pages/2_Fuel.py", "Fuel", "water_drop"), ("pages/3_Driver.py", "Driver", "person"),
        ("pages/4_Utilization.py", "Utilization", "monitoring"),
        ("pages/5_Maintenance.py", "Maintenance", "build"),
        ("pages/6_Anomalies.py", "Anomalies", "error"),
        ("pages/7_Audit_Export.py", "Audit Export", "description")]


def _sidebar_nav():
    """Custom sidebar nav (replaces the default page list): icons + status badges."""
    st.sidebar.markdown('<div class="tt-navtitle">Truck Tracker</div>', unsafe_allow_html=True)
    try:
        n_anom = int(db.scalar("SELECT COUNT(*) FROM anomalies", default=0) or 0)
        hard = int(db.scalar("SELECT COUNT(*) FROM eco_flags WHERE hard_safety=1", default=0) or 0)
        overdue = int(db.scalar("SELECT COUNT(*) FROM service_status WHERE due=1", default=0) or 0)
    except Exception:
        n_anom = hard = overdue = 0
    for path, lbl, mic in _NAV:
        badge = ""
        if lbl == "Anomalies" and n_anom:
            badge = f"  ({n_anom})"
        elif lbl == "Driver" and hard:
            badge = "  🔴"
        elif lbl == "Maintenance" and overdue:
            badge = "  🟠"
        try:
            st.sidebar.page_link(path, label=f"{lbl}{badge}", icon=f":material/{mic}:")
        except Exception:
            try:
                st.sidebar.page_link(path, label=f"{lbl}{badge}")
            except Exception:
                st.sidebar.markdown(f'<div class="tt-small">{lbl}{badge}</div>',
                                    unsafe_allow_html=True)
    st.sidebar.markdown('<hr style="margin:.5rem 0"/>', unsafe_allow_html=True)


def page_setup(title):
    """First call on every page: configure, inject CSS, render the sidebar nav."""
    st.set_page_config(page_title=f"{title} · Truck Tracker", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(_CSS, unsafe_allow_html=True)
    _sidebar_nav()


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


# Segmented presets -> (length-seconds | "month" | "custom"), friendly label.
_PERIOD_OPTS = ["7d", "30d", "Month", "Custom"]
_PERIOD_SPEC = {"7d": (7 * 86400, "Last 7 days"), "30d": (30 * 86400, "Last 30 days"),
                "Month": ("month", "This month"), "Custom": ("custom", None)}
_DEFAULT = "30d"


def _day_start(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def period_selector():
    """Sidebar period control (segmented), anchored to the latest data we hold.

    [7d] [30d] [Month] [Custom]. Returns (from_ts, to_ts, label) and shows the
    resolved range in the sidebar.
    """
    st.sidebar.markdown("**Period**")
    choice = st.sidebar.segmented_control("Period", _PERIOD_OPTS, default=_DEFAULT,
                                          label_visibility="collapsed", key="tt_period") or _DEFAULT
    anchor = db.last_data_ts() or int(time.time())
    span, label = _PERIOD_SPEC[choice]

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
    elif span == "month":
        d = datetime.fromtimestamp(anchor, timezone.utc).date().replace(day=1)
        from_ts, to_ts = _day_start(d), anchor
    else:
        from_ts, to_ts = anchor - span, anchor

    st.sidebar.caption(f"Showing {fmt_dt(from_ts, with_time=False)} – "
                       f"{fmt_dt(to_ts, with_time=False)}")
    return from_ts, to_ts, label


def freshness_caption():
    last = db.last_data_ts()
    ingested = db.last_ingest_ts()
    if last:
        age_h = (time.time() - last) / 3600
        dot = STATUS_OK if age_h < 6 else (STATUS_WARN if age_h < 24 else STATUS_CRITICAL)
        st.sidebar.markdown(
            f'<div class="tt-small" style="margin-top:.3rem"><span style="display:inline-block;'
            f'width:8px;height:8px;border-radius:999px;background:{dot};margin-right:.4rem">'
            f'</span>Data as of {fmt_dt(last)} UTC</div>', unsafe_allow_html=True)
    if ingested:
        st.sidebar.caption(f"last ingestion {fmt_dt(ingested)} UTC")
    st.sidebar.markdown(
        '<a class="tt-small" href="https://github.com/bashir-netizen/truck-tracker/tree/main/docs" '
        'target="_blank" style="color:var(--ink-muted)">About this dashboard ↗</a>',
        unsafe_allow_html=True)
