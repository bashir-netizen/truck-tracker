"""Map — the headline view: where the truck went this period (journeys)."""

import pathlib
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402

from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.metric_card import cards_row  # noqa: E402

theme.page_setup("Map")


def day_start(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


# --- date range control ---------------------------------------------------
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
theme.header("Map", f"{frm_d:%d %b} – {to_d:%d %b %Y} · where the truck went")

# --- load data (pure SQL; no geo math in the read layer) ------------------
places = db.q("SELECT place_id, label, lat, lon, visit_count, visit_time_total_s FROM places")
if places.empty:
    empty_state("No places yet",
                "Place detection runs after the first enrichment pass. "
                "Run <code>python -m enrich.run</code> to populate the map.")
    st.stop()
P = {int(r.place_id): r for r in places.itertuples()}

journeys = db.q(
    "SELECT start_ts, end_ts, origin_place_id, dest_place_id, distance_m, duration_s, "
    "fuel_l, leg_count, is_local FROM journeys WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts DESC",
    (from_ts, to_ts))
dwell = db.q(
    "SELECT place_id, SUM(duration_s) dwell, COUNT(*) visits, MAX(ts) last_ts "
    "FROM place_visits WHERE ts BETWEEN ? AND ? GROUP BY place_id", (from_ts, to_ts))
D = {int(r.place_id): r for r in dwell.itertuples()}

# --- corridors in range (aggregate journeys by unordered place pair) ------
agg = defaultdict(lambda: {"n": 0, "km": 0.0, "fuel": 0.0, "last": None})
for j in journeys.itertuples():
    if j.is_local or pd.isna(j.origin_place_id) or pd.isna(j.dest_place_id):
        continue
    a, b = int(j.origin_place_id), int(j.dest_place_id)
    if a == b:
        continue
    key = (min(a, b), max(a, b))
    g = agg[key]
    g["n"] += 1
    g["km"] += (j.distance_m or 0) / 1000
    g["fuel"] += j.fuel_l or 0
    g["last"] = j.start_ts if g["last"] is None else max(g["last"], j.start_ts)

corr = []
for (a, b), g in agg.items():
    if a not in P or b not in P:
        continue
    corr.append({
        "key": f"{a}-{b}", "a": a, "b": b,
        "A": P[a].label, "B": P[b].label, "journeys": g["n"],
        "km": round(g["km"]), "lpk": round(g["fuel"] / g["km"] * 100, 1) if g["km"] else None,
        "last": theme.fmt_dt(g["last"], with_time=False),
        "src": [P[a].lon, P[a].lat], "dst": [P[b].lon, P[b].lat]})
corr_df = pd.DataFrame(corr).sort_values(["journeys", "km"], ascending=False).reset_index(drop=True) \
    if corr else pd.DataFrame()

# places visited in range (dwell > 0), for the bubble layer
pv = []
for pid, r in D.items():
    if pid not in P:
        continue
    pv.append({"place_id": pid, "label": P[pid].label, "lat": P[pid].lat, "lon": P[pid].lon,
               "dwell_s": int(r.dwell or 0), "visits": int(r.visits or 0)})
places_df = pd.DataFrame(pv).sort_values("dwell_s", ascending=False).reset_index(drop=True) \
    if pv else pd.DataFrame()

map_slot = st.container()  # render map last (after panels set selection), show first

# --- Period summary -------------------------------------------------------
span = to_ts - from_ts


def route_stats(lo, hi):
    j = db.q("SELECT distance_m FROM journeys WHERE is_local=0 AND start_ts BETWEEN ? AND ?", (lo, hi))
    return {
        "days": db.scalar("SELECT COUNT(DISTINCT date(start_ts,'unixepoch')) FROM trips "
                          "WHERE start_ts BETWEEN ? AND ?", (lo, hi), 0),
        "journeys": len(j),
        "km": (j["distance_m"].sum() / 1000) if not j.empty else 0,
        "places": db.scalar("SELECT COUNT(DISTINCT place_id) FROM place_visits "
                            "WHERE ts BETWEEN ? AND ?", (lo, hi), 0)}


cur = route_stats(from_ts, to_ts)
prev = route_stats(from_ts - span, from_ts)
has_prev = db.scalar("SELECT COUNT(*) FROM trips WHERE start_ts < ?", (from_ts,), 0) > 0
longest = db.q("SELECT distance_m, start_ts FROM journeys WHERE is_local=0 AND start_ts BETWEEN ? AND ? "
               "ORDER BY distance_m DESC LIMIT 1", (from_ts, to_ts))


def delta(a, b):
    return round(a - b) if has_prev else None


cards_row([
    dict(label="Active days", value=cur["days"], delta=delta(cur["days"], prev["days"])),
    dict(label="Route trips", value=cur["journeys"], delta=delta(cur["journeys"], prev["journeys"])),
    dict(label="Route distance", value=f"{cur['km']:,.0f}", unit="km",
         delta=delta(cur["km"], prev["km"])),
    dict(label="Places visited", value=cur["places"], delta=delta(cur["places"], prev["places"])),
    dict(label="Longest trip", value=f"{longest.iloc[0].distance_m / 1000:,.0f}" if not longest.empty else "—",
         unit="km", hint=theme.fmt_dt(longest.iloc[0].start_ts, False) if not longest.empty else None),
])

st.markdown('<hr/>', unsafe_allow_html=True)

# --- Top routes / Top places (selectable) ---------------------------------
sel_corridor, sel_place = None, None
left, right = st.columns(2)
with left:
    st.subheader("Top routes")
    if corr_df.empty:
        empty_state("No completed routes in this period",
                    "The truck may have been parked or doing yard activity only.")
    else:
        show = corr_df.head(5).assign(Route=lambda d: d["A"] + " – " + d["B"])
        ev = st.dataframe(
            show[["Route", "journeys", "km"]], hide_index=True, use_container_width=True,
            on_select="rerun", selection_mode="single-row", key="routes_tbl",
            column_config={"journeys": st.column_config.NumberColumn("Trips"),
                           "km": st.column_config.NumberColumn("Total km", format="%d")})
        if ev.selection.rows:
            sel_corridor = show.iloc[ev.selection.rows[0]]["key"]

with right:
    st.subheader("Top places")
    if places_df.empty:
        empty_state("No places visited in this period")
    else:
        show = places_df.head(5).copy()
        show["Time there"] = show["dwell_s"].apply(theme.fmt_dur)
        ev = st.dataframe(
            show[["label", "Time there", "visits"]], hide_index=True, use_container_width=True,
            on_select="rerun", selection_mode="single-row", key="places_tbl",
            column_config={"label": "Place", "visits": st.column_config.NumberColumn("Visits")})
        if ev.selection.rows:
            sel_place = int(show.iloc[ev.selection.rows[0]]["place_id"])

# --- render the map into the top slot --------------------------------------
with map_slot:
    layers = []
    if not corr_df.empty:
        m = corr_df.copy()
        m["width"] = m["journeys"].clip(lower=1).add(1).clip(upper=8)
        m["name"] = (m["A"] + " – " + m["B"] + " · " + m["journeys"].astype(str)
                     + " trips · " + m["km"].astype(str) + " km · "
                     + m["lpk"].fillna("—").astype(str) + " L/100km · last " + m["last"])

        def line_color(row):
            if sel_corridor is None:
                return theme.CORRIDOR_RGB + [180]
            return theme.CORRIDOR_RGB + ([255] if row["key"] == sel_corridor else [40])
        m["color"] = m.apply(line_color, axis=1)
        m["width"] = m.apply(lambda r: 8 if r["key"] == sel_corridor else r["width"], axis=1)
        layers.append(pdk.Layer(
            "LineLayer", data=m, get_source_position="src", get_target_position="dst",
            get_color="color", get_width="width", width_units="pixels",
            width_min_pixels=2, width_max_pixels=8, pickable=True))

    if not places_df.empty:
        pl = places_df.copy()
        pl["radius"] = (pl["dwell_s"].clip(lower=1) ** 0.5 * 40).clip(lower=200)
        pl["name"] = pl["label"] + " · " + pl["dwell_s"].apply(theme.fmt_dur) + " · " \
            + pl["visits"].astype(str) + " visits"
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=pl, get_position=["lon", "lat"], get_radius="radius",
            get_fill_color=theme.PLACE_RGB + [200], radius_min_pixels=5, radius_max_pixels=28,
            pickable=True, stroked=True, get_line_color=[255, 255, 255, 230], line_width_min_pixels=1))

    if not corr_df.empty or not places_df.empty:
        if sel_place is not None and sel_place in P:
            view = pdk.ViewState(latitude=P[sel_place].lat, longitude=P[sel_place].lon, zoom=11)
        else:
            anchor = places_df if not places_df.empty else pd.DataFrame(
                {"lat": [P[k].lat for k in P], "lon": [P[k].lon for k in P]})
            view = pdk.ViewState(latitude=float(anchor["lat"].mean()),
                                 longitude=float(anchor["lon"].mean()), zoom=6)
        st.pydeck_chart(pdk.Deck(
            layers=layers, initial_view_state=view, map_style=theme.MAP_STYLE,
            tooltip={"html": "<b>{name}</b>",
                     "style": {"backgroundColor": theme.INK, "color": "white",
                               "fontSize": "12px", "borderRadius": "8px"}}))
    else:
        empty_state("No completed routes in this period",
                    "The truck may have been parked or doing yard activity only.")
    st.caption("Blue lines: routes (thicker = more trips). Dark bubbles: places "
               "(bigger = more time spent). Select a row below to highlight or centre it.")

# --- Journeys table (the statement-reconciliation ledger) -----------------
st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Journeys")
if journeys.empty:
    empty_state("No journeys in this period")
else:
    def lbl(pid):
        return P[int(pid)].label if not pd.isna(pid) and int(pid) in P else "—"
    jt = pd.DataFrame({
        "Date": pd.to_datetime(journeys["start_ts"], unit="s", utc=True),
        "From": journeys["origin_place_id"].apply(lbl),
        "To": journeys["dest_place_id"].apply(lbl),
        "Legs": journeys["leg_count"],
        "Distance (km)": (journeys["distance_m"] / 1000).round(0),
        "Duration (h)": (journeys["duration_s"] / 3600).round(1),
        "Fuel (L)": journeys["fuel_l"].round(0),
        "Type": journeys["is_local"].map({1: "local", 0: "route"}),
    })
    st.dataframe(jt, hide_index=True, use_container_width=True, column_config={
        "Date": st.column_config.DatetimeColumn("Date", format="DD MMM YYYY")})

with st.expander("Edit place labels"):
    pyaml = ROOT / "places.yaml"
    st.markdown(
        "Places are auto-named from Wialon's geocoding. To rename one, add an "
        "entry to `places.yaml` (committed to the repo) keyed by coordinates — "
        "the nearest place within 300 m adopts your label. Then re-run "
        "`enrich.run` (or wait for the scheduled job).")
    st.code((pyaml.read_text() if pyaml.exists()
             else "# places.yaml (create this file)\n"
                  "- label: Athi River yard\n  lat: -1.437\n  lon: 36.961\n"),
            language="yaml")
