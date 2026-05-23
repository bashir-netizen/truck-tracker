"""Map — multi-trip view: every trip as a colour-by-date track with direction
arrows, event overlays (fuel fills, harsh events, long unknown stops), a date
legend/filter, click-to-investigate event drill-in, and in-dashboard playback of
any trip. Per-trip paths come from the derived `trip_paths` table; playback is the
self-contained deck.gl player in components/track_player.py."""

import importlib
import json
import math
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import config  # noqa: E402
from app.components import db, theme, track_player  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.format import format_kes, relative_day  # noqa: E402
from app.components.metric_card import metric_card  # noqa: E402
from billing import estimate  # noqa: E402

importlib.reload(config)
importlib.reload(theme)

theme.page_setup("Map")
ROUTE_CLASSES = ["long_haul", "regional", "local"]
FILTER_TO_CHAR = {"All": None, "Long haul": "long_haul", "Regional": "regional", "Local": "local"}
CLASS_LABELS = getattr(theme, "CLASS_LABELS", {
    "long_haul": "long haul", "regional": "regional", "local": "local", "yard": "yard"})
CLASS_WIDTH = getattr(theme, "CLASS_WIDTH", {
    "long_haul": 6, "regional": 5, "local": 4, "yard": 3})
MAX_TRIPS = 50
LONG_STOP_S = 7200          # 2 h
EVENT_RGB = {"fill": [29, 111, 184], "harsh": [196, 61, 47], "stop": [91, 103, 112]}
EVENT_NAME = {"fill": "Fuel fill", "harsh": "Harsh event", "stop": "Long stop (unknown place)"}
# A small right-pointing arrow; tinted dark, drawn along each track to show heading.
_ARROW_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' "
              "viewBox='0 0 24 24'><path d='M3 12 H17 M12 6 L19 12 L12 18' "
              "fill='none' stroke='%230e1116' stroke-width='2.6' stroke-linecap='round' "
              "stroke-linejoin='round'/></svg>")
ARROW_ICON = {"url": "data:image/svg+xml;charset=utf-8," + quote(_ARROW_SVG),
              "width": 24, "height": 24, "anchorX": 12, "anchorY": 12}
TYPE_LABELS = {"harsh_accel": "Harsh acceleration", "harsh_brake": "Harsh braking",
               "harsh_corner": "Harsh cornering", "speeding": "Speeding", "idling": "Idling"}


def day_start(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def fit_view(lats, lons):
    if not lats:
        return pdk.ViewState(latitude=0.5, longitude=37.5, zoom=5.5)  # Kenya
    clat, clon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    span = max(max(lats) - min(lats), max(lons) - min(lons), 0.02)
    return pdk.ViewState(latitude=clat, longitude=clon,
                         zoom=max(4.5, min(13.0, math.log2(360.0 / span) - 1)))


def haversine_km(la0, lo0, la1, lo1):
    r = 6371.0
    p0, p1 = math.radians(la0), math.radians(la1)
    dp, dl = math.radians(la1 - la0), math.radians(lo1 - lo0)
    a = math.sin(dp / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def sample_arrows(path, every_km=5.0):
    """Arrow markers (position + heading) every ~every_km along a [[lon,lat],…] path."""
    out, acc = [], 0.0
    for i in range(1, len(path)):
        lo0, la0 = path[i - 1]
        lo1, la1 = path[i]
        acc += haversine_km(la0, lo0, la1, lo1)
        if acc >= every_km:
            acc = 0.0
            dy = la1 - la0
            dx = (lo1 - lo0) * math.cos(math.radians((la0 + la1) / 2))
            ang = math.degrees(math.atan2(dy, dx))  # CCW from east; arrow SVG points east
            out.append({"position": [lo1, la1], "angle": ang, "icon": ARROW_ICON})
    return out


# --- date range control (sidebar) -----------------------------------------
today = date.today()
month_start = today.replace(day=1)
if "map_range" not in st.session_state:
    st.session_state.map_range = (month_start, today)
st.sidebar.markdown("**Period**")
b1, b2, b3 = st.sidebar.columns(3)
if b1.button("Month", use_container_width=True):
    st.session_state.map_range = (month_start, today)
if b2.button("30d", use_container_width=True):
    st.session_state.map_range = (today - timedelta(days=30), today)
if b3.button("7d", use_container_width=True):
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
places = db.q("SELECT place_id, label, lat, lon, radius_m, needs_label FROM places")
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

# --- date legend / filter -------------------------------------------------
day_counts = tdf.groupby("day").size().to_dict()
st.session_state.setdefault("map_day", None)
st.markdown('<div class="tt-eyebrow" style="margin:.3rem 0 .2rem">Trips by day — click to '
            'filter</div>', unsafe_allow_html=True)
legend_cols = st.columns(min(8, max(1, len(day_counts) + 1)))
with legend_cols[0]:
    if st.button("All dates", use_container_width=True,
                 type="primary" if st.session_state.map_day is None else "secondary"):
        st.session_state.map_day = None
        st.rerun()
for i, d in enumerate(sorted(day_counts, reverse=True)[:7], start=1):
    swatch = theme.date_color(d)
    lbl = datetime.strptime(d, "%Y-%m-%d").strftime("%d %b")
    with legend_cols[i]:
        if st.button(f"{lbl} · {day_counts[d]}", key=f"day_{d}", use_container_width=True,
                     type="primary" if st.session_state.map_day == d else "secondary"):
            st.session_state.map_day = None if st.session_state.map_day == d else d
            st.rerun()
        st.markdown(f'<div style="height:3px;border-radius:2px;background:{swatch};'
                    f'margin:-.4rem .2rem .4rem"></div>', unsafe_allow_html=True)

if st.session_state.map_day:
    tdf = tdf[tdf["day"] == st.session_state.map_day]

# performance cap: only for large ranges (a normal month renders fine)
capped = (to_ts - from_ts) / 86400 > 30 and len(tdf) > MAX_TRIPS
if capped:
    tdf = tdf.head(MAX_TRIPS)

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
    pretty = datetime.fromtimestamp(int(r.start_ts), timezone.utc).strftime("%d %b %H:%M")
    km = round((r.distance_m or 0) / 1000)
    records.append({
        "start_ts": int(r.start_ts), "end_ts": int(r.end_ts),
        "journey_class": cls, "day": r.day, "distance_km": km,
        "path": path, "fallback": fallback,
        "name": f"{pretty} · {CLASS_LABELS.get(cls, cls)} · {km} km"
                + (" · GPS path missing (straight line)" if fallback else ""),
        "color": theme.hex_to_rgb(theme.date_color(r.day)),
        "width": CLASS_WIDTH.get(cls, 4)})

# --- places (period dwell) ------------------------------------------------
dwell = db.q("SELECT place_id, SUM(duration_s) dwell, COUNT(*) visits, MAX(ts) last_ts "
             "FROM place_visits WHERE ts BETWEEN ? AND ? GROUP BY place_id", (from_ts, to_ts))
places_df = pd.DataFrame([
    {"place_id": int(r.place_id), "label": P[int(r.place_id)].label, "lat": P[int(r.place_id)].lat,
     "lon": P[int(r.place_id)].lon, "dwell_s": int(r.dwell or 0), "visits": int(r.visits or 0),
     "last_ts": int(r.last_ts or 0)}
    for r in dwell.itertuples() if int(r.place_id) in P]) if not dwell.empty else pd.DataFrame()
if not places_df.empty:
    places_df = places_df.sort_values("dwell_s", ascending=False).reset_index(drop=True)

# --- events (only loaded when the Events layer is on) ---------------------
events = []
if show_events:
    lo, hi = from_ts, to_ts
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
    pl["radius"] = (pl["dwell_s"].clip(lower=1) ** 0.5 * 40).clip(lower=200)
    pl["fill"] = [theme.PLACE_RGB + [200]] * len(pl)
    pl["name"] = pl["label"] + " · " + pl["dwell_s"].apply(theme.fmt_dur)
    layers.append(pdk.Layer(
        "ScatterplotLayer", id="places", data=pl, get_position=["lon", "lat"],
        get_radius="radius", get_fill_color="fill", radius_min_pixels=5, radius_max_pixels=30,
        pickable=True, stroked=True, get_line_color=[255, 255, 255, 230], line_width_min_pixels=1))

if show_trips and records:
    solid = pd.DataFrame([r for r in records if not r["fallback"]])
    dashed = pd.DataFrame([r for r in records if r["fallback"]])
    if not solid.empty:
        layers.append(pdk.Layer(
            "PathLayer", id="trips", data=solid, get_path="path", get_color="color",
            get_width="width", width_units="pixels", width_min_pixels=2, width_max_pixels=10,
            opacity=0.75, pickable=True, cap_rounded=True, joint_rounded=True))
        arrows = []
        for r in records:
            if not r["fallback"]:
                arrows += sample_arrows(r["path"])
        if arrows:
            layers.append(pdk.Layer(
                "IconLayer", id="arrows", data=arrows, get_icon="icon", get_position="position",
                get_angle="angle", get_size=15, size_units="pixels", pickable=False))
    if not dashed.empty:  # NULL-path trips: faint straight line, flagged in the tooltip
        layers.append(pdk.Layer(
            "PathLayer", id="trips_missing", data=dashed, get_path="path",
            get_color=[138, 146, 163, 150], get_width=2, width_units="pixels",
            width_min_pixels=1, pickable=True))

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
    use_container_width=True)

# legend strip under the map
leg = (f'<span style="color:{theme.MUTED}">tracks coloured by day · width by class</span>'
       ' &nbsp; '
       f'<span class="dot" style="background:rgb{tuple(EVENT_RGB["fill"])}"></span>fill'
       f' &nbsp;<span class="dot" style="background:rgb{tuple(EVENT_RGB["harsh"])}"></span>harsh'
       f' &nbsp;<span class="dot" style="background:rgb{tuple(EVENT_RGB["stop"])}"></span>long stop')
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
if clicked_event:
    st.session_state["sel_event"] = clicked_event
elif objects.get("trips"):
    ts = int(objects["trips"][0]["start_ts"])
    st.session_state["play_trip"] = ts
    st.session_state.pop("sel_event", None)

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
        if st.button("Clear event", use_container_width=True):
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
                 use_container_width=True,
                 column_config={"label": "Place", "visits": st.column_config.NumberColumn("Visits")})

unlabeled = db.q("SELECT label, ROUND(lat,5) lat, ROUND(lon,5) lon FROM places WHERE needs_label=1")
if not unlabeled.empty:
    with st.expander(f"{len(unlabeled)} place(s) need a better name — edit places.yaml"):
        st.dataframe(unlabeled.rename(columns={"label": "Current name", "lat": "Lat", "lon": "Lon"}),
                     hide_index=True, use_container_width=True)
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
                    hint=f"at KES {diesel}/L pump price")
    if any(v is not None for v in km_rates.values()):
        total, _, incl, excl = estimate.revenue_by_class(all_routes, km_rates)
        foot = "Includes: " + ", ".join(CLASS_LABELS[c] for c in incl)
        if excl:
            foot += " · Excludes: " + ", ".join(CLASS_LABELS[c] for c in excl) + " (no rate)"
        with cc[1]:
            metric_card("Est. revenue", format_kes(total), hint=foot)
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
