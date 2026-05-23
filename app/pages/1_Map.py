"""Map — multi-trip view: every trip as a colour-by-date track with direction
arrows, event overlays (fuel fills, harsh events, long unknown stops), a date
legend/filter, click-to-investigate event drill-in, and in-dashboard playback of
any trip. Per-trip paths come from the derived `trip_paths` table; playback is the
self-contained deck.gl player in components/track_player.py."""

import importlib
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import config  # noqa: E402
from app.components import db, journey_view, theme, track_player  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.format import format_kes, relative_day  # noqa: E402
from app.components.map_helpers import (ARROW_KM, EVENT_NAME, EVENT_RGB,  # noqa: E402
                                        TYPE_LABELS, day_start, fit_view,
                                        haversine_km, sample_arrows)
from app.components.metric_card import metric_card  # noqa: E402
from billing import estimate  # noqa: E402

importlib.reload(config)
importlib.reload(theme)

theme.page_setup("Map")

# Mode 2 — Journey View: a selected round trip (?round_trip=<id>, or the session
# handoff from the Overview button) shows that one trip and stops here. No selection
# -> Mode 1 (period overview) below, unchanged.
_jrt = st.query_params.get("round_trip")
if _jrt is None and "journey_rt" in st.session_state:
    _jrt = str(st.session_state["journey_rt"])
    st.query_params["round_trip"] = _jrt          # restore to the URL if switch_page dropped it
if _jrt is not None:
    st.session_state.pop("journey_rt", None)
    try:
        _rtid = int(_jrt)
    except (TypeError, ValueError):
        st.query_params.clear()
    else:
        journey_view.render(_rtid)
        st.stop()

ROUTE_CLASSES = ["long_haul", "regional", "local"]
FILTER_TO_CHAR = {"All": None, "Long haul": "long_haul", "Regional": "regional", "Local": "local"}
CLASS_LABELS = getattr(theme, "CLASS_LABELS", {
    "long_haul": "long haul", "regional": "regional", "local": "local", "yard": "yard"})
CLASS_WIDTH = getattr(theme, "CLASS_WIDTH", {
    "long_haul": 6, "regional": 5, "local": 4, "yard": 3})
# A dwell-suggested type ("customer?") -> the places.yaml type it maps to, and a
# phrase for the mismatch callout. rest?/overnight? have no settable type -> no callout.
SUGGEST_REAL = {"transit?": "transit", "customer?": "customer", "depot?": "depot"}
SUGGEST_PHRASE = {"transit": "a transit stop", "customer": "a customer site",
                  "depot": "your depot / home base"}
MAX_TRIPS = 50
LONG_STOP_S = 7200          # 2 h
# Event constants, the arrow icon, and the pure geo/format helpers now live in
# app/components/map_helpers.py (shared with the Journey View).


def nearest_place(lat, lon, max_km=3.0):
    """Label of the nearest known place within max_km, else None."""
    best, bestd = None, max_km
    for p in P.values():
        d = haversine_km(lat, lon, p.lat, p.lon)
        if d < bestd:
            best, bestd = p.label, d
    return best


# --- date range control (sidebar) -----------------------------------------
today = date.today()
month_start = today.replace(day=1)
if "map_range" not in st.session_state:
    st.session_state.map_range = (month_start, today)
st.sidebar.markdown("**Period**")
b1, b2, b3 = st.sidebar.columns(3)
if b1.button("Month", width="stretch"):
    st.session_state.map_range = (month_start, today)
if b2.button("30d", width="stretch"):
    st.session_state.map_range = (today - timedelta(days=30), today)
if b3.button("7d", width="stretch"):
    st.session_state.map_range = (today - timedelta(days=7), today)
picked = st.sidebar.date_input("Date range", value=st.session_state.map_range,
                               label_visibility="collapsed")
if isinstance(picked, tuple) and len(picked) == 2:
    st.session_state.map_range = picked
frm_d, to_d = st.session_state.map_range
from_ts, to_ts = day_start(frm_d), day_start(to_d) + 86399
theme.freshness_caption()
theme.header("Map", f"{frm_d:%d %b} – {to_d:%d %b %Y} · every trip, with events and playback")

# --- places ---------------------------------------------------------------
places = db.q("SELECT place_id, label, lat, lon, radius_m, needs_label, type FROM places")
if places.empty:
    empty_state("No places yet",
                "Run <code>python -m enrich.run</code> to populate the map.")
    st.stop()
P = {int(r.place_id): r for r in places.itertuples()}

# --- per-trip paths (derived) + trip coords (raw) -------------------------
trips = db.q(
    "SELECT tp.start_ts, tp.end_ts, tp.journey_class, tp.path_geojson, "
    "       t.start_lat, t.start_lon, t.end_lat, t.end_lon, t.distance_m "
    "FROM trip_paths tp JOIN trips t "
    "  ON t.unit_id = tp.unit_id AND t.start_ts = tp.start_ts "
    "WHERE tp.start_ts BETWEEN ? AND ? ORDER BY tp.start_ts DESC", (from_ts, to_ts))

journeys = db.q(
    "SELECT journey_character FROM journeys WHERE start_ts BETWEEN ? AND ?", (from_ts, to_ts))
counts = journeys["journey_character"].value_counts().to_dict() if not journeys.empty else {}
parts = [f"<b>{int(counts[c])}</b> {CLASS_LABELS[c]}"
         for c in ["long_haul", "regional", "local", "yard"] if counts.get(c, 0)]
st.markdown(f'<div class="tt-mix">This period: {" · ".join(parts)}</div>' if parts
            else '<div class="tt-mix">No trips this period.</div>', unsafe_allow_html=True)

if trips.empty:
    empty_state("No trips in this period", "Try a wider range in the sidebar.")
    st.stop()

# --- controls: class filter · layer toggles -------------------------------
c_left, c_right = st.columns([2, 3])
with c_left:
    choice = st.segmented_control("Class", list(FILTER_TO_CHAR), default="All", key="class_filter")
char = FILTER_TO_CHAR.get(choice or "All")
with c_right:
    tg = st.columns(3)
    show_trips = tg[0].toggle("Trips", value=True, key="lyr_trips")
    show_places = tg[1].toggle("Places", value=True, key="lyr_places")
    show_events = tg[2].toggle("Events", value=True, key="lyr_events")

tdf = trips if char is None else trips[trips["journey_class"] == char]

# date string per trip + colour
tdf = tdf.assign(
    day=tdf["start_ts"].map(lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")))

# marker key — what the trip start/end/direction glyphs mean, by the controls so
# it's seen without scrolling down to the under-map legend.
_KEY_RED = theme.TRIP_DATE_PALETTE[0]
st.markdown(
    f'<div class="tt-micro" style="display:flex;gap:1.2rem;flex-wrap:wrap;'
    f'color:{theme.MUTED};margin:.1rem 0 .5rem">'
    f'<span><span style="color:{_KEY_RED}">●</span> Trip start</span>'
    f'<span><span style="color:{_KEY_RED}">○</span> Trip end</span>'
    f'<span><span style="color:{theme.INK};font-weight:700">→</span> Direction</span>'
    '</div>', unsafe_allow_html=True)

# --- date legend / filter -------------------------------------------------
day_counts = tdf.groupby("day").size().to_dict()
ordered_days = sorted(day_counts, reverse=True)            # newest first (legend order)
DAY_COLOR = theme.date_colors(ordered_days)                # sequential; no adjacent clashes
st.session_state.setdefault("map_day", None)
st.markdown('<div class="tt-eyebrow" style="margin:.3rem 0 .2rem">Trips by day — click to '
            'filter</div>', unsafe_allow_html=True)
legend_cols = st.columns(min(8, max(1, len(ordered_days) + 1)))
with legend_cols[0]:
    if st.button("All dates", width="stretch",
                 type="primary" if st.session_state.map_day is None else "secondary"):
        st.session_state.map_day = None
        st.rerun()
for i, d in enumerate(ordered_days[:7], start=1):
    lbl = datetime.strptime(d, "%Y-%m-%d").strftime("%d %b")
    with legend_cols[i]:
        if st.button(f"{lbl} · {day_counts[d]}", key=f"day_{d}", width="stretch",
                     type="primary" if st.session_state.map_day == d else "secondary"):
            st.session_state.map_day = None if st.session_state.map_day == d else d
            st.rerun()
        st.markdown(f'<div style="height:3px;border-radius:2px;background:{DAY_COLOR[d]};'
                    f'margin:-.4rem .2rem .4rem"></div>', unsafe_allow_html=True)

# A selected day filters ALL layers (trips, places, events) via this window.
if st.session_state.map_day:
    sel_day = st.session_state.map_day
    eff_from = day_start(datetime.strptime(sel_day, "%Y-%m-%d").date())
    eff_to = eff_from + 86399
    tdf = tdf[tdf["day"] == sel_day]
else:
    eff_from, eff_to = from_ts, to_ts

# performance cap: only for large ranges (a normal month renders fine)
capped = (to_ts - from_ts) / 86400 > 30 and len(tdf) > MAX_TRIPS
if capped:
    tdf = tdf.head(MAX_TRIPS)

# per-date chronological index for "Trip N of M"
n_in_day = {}
for day, grp in tdf.groupby("day"):
    for i, ts in enumerate(sorted(grp["start_ts"]), 1):
        n_in_day[int(ts)] = (i, len(grp))

# build per-trip records
records = []
for r in tdf.itertuples():
    path = json.loads(r.path_geojson) if isinstance(r.path_geojson, str) else None
    fallback = path is None
    if fallback:  # NULL path -> dashed straight line start->end
        if r.start_lat is None or r.end_lat is None:
            continue
        path = [[r.start_lon, r.start_lat], [r.end_lon, r.end_lat]]
    cls = r.journey_class or "local"
    km = round((r.distance_m or 0) / 1000)
    n_of, m_of = n_in_day.get(int(r.start_ts), (1, 1))
    a = nearest_place(path[0][1], path[0][0]) or "start"
    b = nearest_place(path[-1][1], path[-1][0]) or "end"
    t0 = datetime.fromtimestamp(int(r.start_ts), timezone.utc).strftime("%d %b %H:%M")
    t1 = datetime.fromtimestamp(int(r.end_ts), timezone.utc).strftime("%H:%M")
    records.append({
        "start_ts": int(r.start_ts), "end_ts": int(r.end_ts),
        "journey_class": cls, "day": r.day, "distance_km": km,
        "path": path, "fallback": fallback,
        "name": f"Trip {n_of} of {m_of} · {t0}→{t1} · {a}→{b} · {km} km"
                + (" · GPS path missing" if fallback else ""),
        "color": theme.hex_to_rgb(DAY_COLOR[r.day]),
        "width": CLASS_WIDTH.get(cls, 4)})

# --- places (period dwell) ------------------------------------------------
dwell = db.q("SELECT place_id, SUM(duration_s) dwell, COUNT(*) visits, MAX(ts) last_ts "
             "FROM place_visits WHERE ts BETWEEN ? AND ? GROUP BY place_id", (eff_from, eff_to))
places_df = pd.DataFrame([
    {"place_id": int(r.place_id), "label": P[int(r.place_id)].label, "lat": P[int(r.place_id)].lat,
     "lon": P[int(r.place_id)].lon, "dwell_s": int(r.dwell or 0), "visits": int(r.visits or 0),
     "last_ts": int(r.last_ts or 0), "type": P[int(r.place_id)].type or "destination"}
    for r in dwell.itertuples() if int(r.place_id) in P]) if not dwell.empty else pd.DataFrame()
if not places_df.empty:
    places_df = places_df.sort_values("dwell_s", ascending=False).reset_index(drop=True)

# --- events (only loaded when the Events layer is on) ---------------------
events = []
if show_events:
    lo, hi = eff_from, eff_to
    for r in db.q("SELECT ts, lat, lon, volume_l FROM fillings WHERE ts BETWEEN ? AND ?",
                  (lo, hi)).itertuples():
        if r.lat is not None:
            events.append({"kind": "fill", "ts": int(r.ts), "lat": r.lat, "lon": r.lon,
                           "detail": f"{r.volume_l:.0f} L filled", "radius": 9})
    harsh = db.q(
        "SELECT e.ts, e.lat, e.lon, e.type, f.severity FROM eco_events e "
        "JOIN eco_flags f ON f.unit_id=e.unit_id AND f.ts=e.ts AND f.type=e.type "
        "WHERE e.ts BETWEEN ? AND ?", (lo, hi))
    sev_r = {"extreme": 12, "medium": 8, "mild": 6}
    for r in harsh.itertuples():
        if r.lat is not None:
            events.append({"kind": "harsh", "ts": int(r.ts), "lat": r.lat, "lon": r.lon,
                           "detail": f"{TYPE_LABELS.get(r.type, r.type)} ({r.severity or 'n/a'})",
                           "radius": sev_r.get(r.severity, 7)})
    # long stops (>2h) outside every known place radius (display-time geofilter)
    for r in db.q("SELECT start_ts, duration_s, lat, lon FROM stops "
                  "WHERE duration_s >= ? AND start_ts BETWEEN ? AND ?",
                  (LONG_STOP_S, lo, hi)).itertuples():
        if r.lat is None:
            continue
        inside = any(haversine_km(r.lat, r.lon, p.lat, p.lon) * 1000 <= (p.radius_m or 0)
                     for p in P.values())
        if not inside:
            events.append({"kind": "stop", "ts": int(r.start_ts), "lat": r.lat, "lon": r.lon,
                           "detail": f"Stopped {theme.fmt_dur(r.duration_s)} (no known place)",
                           "radius": 9})


def containing_trip(ts):
    for rec in records:
        if rec["start_ts"] <= ts <= rec["end_ts"]:
            return rec
    return None


# --- build map layers -----------------------------------------------------
layers = []
all_lats = [pt[1] for rec in records for pt in rec["path"]]
all_lons = [pt[0] for rec in records for pt in rec["path"]]

if show_places and not places_df.empty:
    pl = places_df.copy()
    pl["type"] = pl["type"].fillna("destination")
    transit = pl["type"] == "transit"   # transit stops drawn smaller + lighter
    pl["radius"] = ((pl["dwell_s"].clip(lower=1) ** 0.5 * 40).clip(lower=200)
                    * transit.map({True: 0.5, False: 1.0}))
    pl["fill"] = [theme.PLACE_RGB + ([110] if t == "transit" else [200]) for t in pl["type"]]
    pl["name"] = pl["label"] + " · " + pl["type"] + " · " + pl["dwell_s"].apply(theme.fmt_dur)
    layers.append(pdk.Layer(
        "ScatterplotLayer", id="places", data=pl, get_position=["lon", "lat"],
        get_radius="radius", get_fill_color="fill", radius_min_pixels=4, radius_max_pixels=30,
        pickable=True, stroked=True, get_line_color=[255, 255, 255, 230], line_width_min_pixels=1))

if show_trips and records:
    solid = pd.DataFrame([r for r in records if not r["fallback"]])
    dashed = pd.DataFrame([r for r in records if r["fallback"]])
    if not solid.empty:
        layers.append(pdk.Layer(
            "PathLayer", id="trips", data=solid, get_path="path", get_color="color",
            get_width="width", width_units="pixels", width_min_pixels=2, width_max_pixels=10,
            pickable=True, cap_rounded=True, joint_rounded=True))
        arrows = []
        for r in records:
            if not r["fallback"]:
                arrows += sample_arrows(r["path"], ARROW_KM.get(r["journey_class"], 3.0),
                                        min_arrows=2 if r["journey_class"] == "yard" else 0)
        if arrows:
            layers.append(pdk.Layer(
                "IconLayer", id="arrows", data=arrows, get_icon="icon", get_position="position",
                get_angle="angle", get_size=15, size_units="pixels", pickable=False))
    if not dashed.empty:  # NULL-path trips: faint straight line, flagged in the tooltip
        layers.append(pdk.Layer(
            "PathLayer", id="trips_missing", data=dashed, get_path="path",
            get_color=[138, 146, 163, 150], get_width=2, width_units="pixels",
            width_min_pixels=1, pickable=True))
    # start (filled dot) + end (hollow ring) markers, above paths & places
    starts = [{"p": r["path"][0], "color": r["color"]} for r in records if not r["fallback"]]
    ends = [{"p": r["path"][-1], "color": r["color"]} for r in records if not r["fallback"]]
    if starts:
        layers.append(pdk.Layer(
            "ScatterplotLayer", id="trip_start", data=starts, get_position="p",
            get_fill_color="color", get_radius=9, radius_units="pixels", radius_min_pixels=5,
            stroked=True, get_line_color=[255, 255, 255], line_width_units="pixels",
            get_line_width=2, pickable=False))
    if ends:
        layers.append(pdk.Layer(
            "ScatterplotLayer", id="trip_end", data=ends, get_position="p",
            get_fill_color=[255, 255, 255], get_radius=8, radius_units="pixels",
            radius_min_pixels=4, stroked=True, get_line_color="color",
            line_width_units="pixels", get_line_width=2.5, pickable=False))

if show_events and events:
    for kind in ("fill", "harsh", "stop"):
        sub = [e for e in events if e["kind"] == kind]
        if sub:
            ed = pd.DataFrame(sub)
            ed["fill"] = [EVENT_RGB[kind] + [235]] * len(ed)
            ed["name"] = EVENT_NAME[kind] + " · " + ed["detail"]
            layers.append(pdk.Layer(
                "ScatterplotLayer", id=f"ev_{kind}", data=ed, get_position=["lon", "lat"],
                get_radius="radius", radius_units="pixels", radius_min_pixels=4,
                get_fill_color="fill", pickable=True, stroked=True,
                get_line_color=[255, 255, 255, 230], line_width_min_pixels=1))

view = fit_view(all_lats, all_lons)
event = st.pydeck_chart(
    pdk.Deck(layers=layers, initial_view_state=view, map_style=theme.MAP_STYLE,
             tooltip={"html": "<b>{name}</b>",
                      "style": {"backgroundColor": theme.INK, "color": "white",
                                "fontSize": "12px", "borderRadius": "8px"}}),
    on_select="rerun", selection_mode="single-object", key="mapsel",
    width="stretch")

# legend strip under the map
leg = (f'<span style="color:{theme.MUTED}">tracks by day · width by class'
       '</span> &nbsp; '
       f'<span class="dot" style="background:rgb{tuple(EVENT_RGB["fill"])}"></span>⛽ fuel'
       f' &nbsp;<span class="dot" style="background:rgb{tuple(EVENT_RGB["harsh"])}"></span>⚠️ violation'
       f' &nbsp;<span class="dot" style="background:rgb{tuple(EVENT_RGB["stop"])}"></span>🅿️ parking')
st.markdown(f'<div class="tt-legend" style="font-weight:500">{leg}</div>', unsafe_allow_html=True)
if capped:
    st.caption(f"Showing the {MAX_TRIPS} most recent trips. Narrow the date range to see all.")

# --- process map selection ------------------------------------------------
objects = {}
if event is not None:
    try:
        objects = event["selection"]["objects"] or {}
    except Exception:
        objects = {}
clicked_event = None
for layer_id, kind in (("ev_harsh", "harsh"), ("ev_fill", "fill"), ("ev_stop", "stop")):
    if objects.get(layer_id):
        o = objects[layer_id][0]
        clicked_event = {"kind": kind, "ts": int(o["ts"]), "lat": o.get("lat"),
                         "lon": o.get("lon"), "detail": o.get("detail", "")}
        break
clicked_place = int(objects["places"][0]["place_id"]) if objects.get("places") else None
if clicked_event:
    st.session_state["sel_event"] = clicked_event
    st.session_state.pop("sel_place", None)
elif clicked_place is not None:
    st.session_state["sel_place"] = clicked_place
    st.session_state.pop("sel_event", None)
elif objects.get("trips"):
    ts = int(objects["trips"][0]["start_ts"])
    st.session_state["play_trip"] = ts
    st.session_state.pop("sel_event", None)
    st.session_state.pop("sel_place", None)

# --- selected place: dwell-signal panel -----------------------------------
sel_place = st.session_state.get("sel_place")
if sel_place is not None:
    prow = db.q("SELECT label, type, median_dwell_s, dwell_pattern_hint, "
                "suggested_type_from_dwell FROM places WHERE place_id=?", (sel_place,))
    if prow.empty:
        st.session_state.pop("sel_place", None)
    else:
        r = prow.iloc[0]
        typ = r["type"] or "destination"
        nvis = db.scalar("SELECT COUNT(*) FROM place_visits WHERE place_id=?", (sel_place,), 0)
        body = (f'<div class="lbl">place</div>'
                f'<div style="margin:.3rem 0 .1rem"><b>{r["label"]}</b> '
                f'<span class="tt-pill neutral">{typ}</span></div>')
        if pd.isna(r["median_dwell_s"]):
            body += '<div class="tt-sub">No dwell records for this place yet.</div>'
        else:
            med = theme.fmt_dur(int(r["median_dwell_s"]))
            pat = r["dwell_pattern_hint"] or "—"
            sug = r["suggested_type_from_dwell"] or "—"
            body += (f'<div class="tt-sub">Visited {nvis} time{"s" if nvis != 1 else ""} · '
                     f'{med} median stay · pattern: {pat} stops</div>'
                     f'<div class="tt-sub">Suggested type (from dwell): <b>{sug}</b></div>')
            mapped = SUGGEST_REAL.get(sug)
            # depot is owner-asserted ground truth — show the suggestion, but don't
            # nag a places.yaml change for it (the dwell summary still flags it).
            if mapped and mapped != typ and typ != "depot":
                body += (f'<div style="margin-top:.4rem;color:var(--accent)">→ This place’s '
                         f'dwell pattern suggests it may be {SUGGEST_PHRASE[mapped]}. '
                         f'Update <code>places.yaml</code> if appropriate.</div>')
        pa, pb = st.columns([3, 1])
        with pa:
            st.markdown(f'<div class="tt-card">{body}</div>', unsafe_allow_html=True)
        with pb:
            if st.button("Clear place", width="stretch"):
                st.session_state.pop("sel_place", None)
                st.rerun()

# --- playback + event drill-in --------------------------------------------
st.markdown("### Playback")
rec_by_ts = {r["start_ts"]: r for r in records}
option_ts = [None] + [r["start_ts"] for r in records]


def trip_label(ts):
    if ts is None:
        return "— pick a trip —"
    r = rec_by_ts.get(ts)
    when = datetime.fromtimestamp(ts, timezone.utc).strftime("%d %b %H:%M")
    return f"{when} · {CLASS_LABELS.get(r['journey_class'], r['journey_class'])} · {r['distance_km']} km"


if st.session_state.get("play_trip") not in option_ts:
    st.session_state["play_trip"] = None
sel_trip_ts = st.selectbox("Play back a trip", option_ts, key="play_trip",
                           format_func=trip_label,
                           on_change=lambda: st.session_state.pop("sel_event", None))

sel_event = st.session_state.get("sel_event")


def positions_between(lo, hi):
    return [list(x) for x in db.q(
        "SELECT lon, lat, ts FROM positions WHERE ts BETWEEN ? AND ? ORDER BY ts",
        (lo, hi)).itertuples(index=False)]


if sel_event:
    ev = sel_event
    when = datetime.fromtimestamp(ev["ts"], timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    ctrip = containing_trip(ev["ts"])
    where = ev.get("detail", "")
    ctx = (f"during the {CLASS_LABELS.get(ctrip['journey_class'], ctrip['journey_class'])} "
           f"trip of {datetime.fromtimestamp(ctrip['start_ts'], timezone.utc):%d %b %H:%M}"
           if ctrip else "while parked (not inside a trip)")
    a, b = st.columns([3, 1])
    with a:
        st.markdown(
            f'<div class="tt-card"><div class="lbl">{EVENT_NAME[ev["kind"]]}</div>'
            f'<div style="margin:.3rem 0 .1rem"><b>{where}</b></div>'
            f'<div class="tt-sub">{when} · {ctx}</div></div>', unsafe_allow_html=True)
    with b:
        if st.button("Clear event", width="stretch"):
            st.session_state.pop("sel_event", None)
            st.rerun()
    if ctrip:
        pts = positions_between(ctrip["start_ts"], ctrip["end_ts"])
        components.html(track_player.player_html(
            pts, color=ctrip["color"], focus_s=ev["ts"] - ctrip["start_ts"],
            label=f'Trip of {datetime.fromtimestamp(ctrip["start_ts"], timezone.utc):%d %b} — '
                  f'playhead at the event'),
            height=track_player.player_total_height())
    else:
        pts = positions_between(ev["ts"] - 300, ev["ts"] + 300)
        components.html(track_player.player_html(
            pts, color=EVENT_RGB[ev["kind"]], focus_s=300,
            label="10-minute window around the event"),
            height=track_player.player_total_height())
elif sel_trip_ts is not None and sel_trip_ts in rec_by_ts:
    r = rec_by_ts[sel_trip_ts]
    pts = positions_between(r["start_ts"], r["end_ts"])
    components.html(track_player.player_html(pts, color=r["color"], label=trip_label(sel_trip_ts)),
                    height=track_player.player_total_height())
else:
    st.caption("Click an event pin on the map, or pick a trip above, to play it back. "
               "The animated head shows direction; scrub or change speed in the player.")

# --- Top places (no regression) -------------------------------------------
st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Top places")
if places_df.empty:
    empty_state("No places visited in this period")
else:
    show = places_df.head(6).copy()
    show["Time there"] = show["dwell_s"].apply(theme.fmt_dur)
    show["Last visited"] = show["last_ts"].apply(relative_day)
    st.dataframe(show[["label", "Time there", "visits", "Last visited"]], hide_index=True,
                 width="stretch",
                 column_config={"label": "Place", "visits": st.column_config.NumberColumn("Visits")})

unlabeled = db.q("SELECT label, ROUND(lat,5) lat, ROUND(lon,5) lon FROM places WHERE needs_label=1")
if not unlabeled.empty:
    with st.expander(f"{len(unlabeled)} place(s) need a better name — edit places.yaml"):
        st.dataframe(unlabeled.rename(columns={"label": "Current name", "lat": "Lat", "lon": "Lon"}),
                     hide_index=True, width="stretch")
        pyaml = ROOT / "places.yaml"
        st.code(pyaml.read_text() if pyaml.exists()
                else "- label: Athi River yard\n  lat: -1.437\n  lon: 36.961\n", language="yaml")

# --- Route summary + cost / what-if (kept; tucked away) --------------------
all_routes = [(jc, dm) for jc, dm in db.q(
    "SELECT journey_character, distance_m FROM journeys WHERE is_local=0 "
    "AND start_ts BETWEEN ? AND ?", (from_ts, to_ts)).itertuples(index=False)]
diesel = config.RATES["diesel_kes_per_l"]
km_rates = {c: config.RATES[f"{c}_kes_per_km"] for c in ROUTE_CLASSES}
filled = db.scalar("SELECT COALESCE(SUM(volume_l),0) FROM fillings WHERE ts BETWEEN ? AND ?",
                   (from_ts, to_ts), 0) or 0

with st.expander("Cost & what-if"):
    cc = st.columns(2)
    with cc[0]:
        metric_card("Fuel bought", format_kes(estimate.fuel_cost(filled, diesel)),
                    confidence="inferred", icon="fuel", hint=f"at KES {diesel}/L pump price")
    if any(v is not None for v in km_rates.values()):
        total, _, incl, excl = estimate.revenue_by_class(all_routes, km_rates)
        foot = "Includes: " + ", ".join(CLASS_LABELS[c] for c in incl)
        if excl:
            foot += " · Excludes: " + ", ".join(CLASS_LABELS[c] for c in excl) + " (no rate)"
        with cc[1]:
            metric_card("Est. revenue", format_kes(total), confidence="inferred",
                        icon="banknote", hint=foot)
    st.markdown("Enter hypothetical KES/km to value this period:")
    w = st.columns(3)
    inputs = {c: w[i].number_input(f"{CLASS_LABELS[c].title()} KES/km", value=km_rates[c],
                                   min_value=0.0, step=5.0, key=f"wi_{c}")
              for i, c in enumerate(ROUTE_CLASSES)}
    if st.button("Calculate", type="primary"):
        total, breakdown, incl, _ = estimate.revenue_by_class(
            all_routes, {c: inputs[c] for c in ROUTE_CLASSES})
        for c in incl:
            b = breakdown[c]
            st.markdown(f"{CLASS_LABELS[c].title()}: {b['km']:,.0f} km × KES {b['rate']:,.0f} "
                        f"= **{format_kes(b['kes'])}**")
        st.markdown(f"**Total: {format_kes(total)}**")
        st.caption("What-if only. Not stored, not an actual estimate.")
