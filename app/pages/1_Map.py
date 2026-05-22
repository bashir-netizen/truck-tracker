"""Map — the headline view: where the truck went and what kind of work it did."""

import importlib
import json
import math
import pathlib
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.format import format_kes, relative_day  # noqa: E402
from app.components.metric_card import metric_card  # noqa: E402
from billing import estimate  # noqa: E402

# Streamlit Cloud can serve a page against a stale, cached config/theme module
# right after a deploy that adds new constants. Re-read both from disk so any
# newly-added attribute (RATES, CLASS_LABELS, …) is always present.
importlib.reload(config)
importlib.reload(theme)

theme.page_setup("Map")
ROUTE_CLASSES = ["long_haul", "regional", "local"]
FILTER_TO_CHAR = {"All": None, "Long haul": "long_haul", "Regional": "regional", "Local": "local"}

# getattr fallbacks guard against Streamlit Cloud serving this page against a
# stale (cached) theme module right after a deploy adds new attributes.
CLASS_LABELS = getattr(theme, "CLASS_LABELS", {
    "long_haul": "long haul", "regional": "regional", "local": "local", "yard": "yard"})
CLASS_COLORS = getattr(theme, "CLASS_COLORS", {
    "long_haul": "#1F6FEB", "regional": "#D97706", "local": "#16A34A", "yard": "#94A3B8"})
TRIP_CLASS_COLORS = getattr(theme, "TRIP_CLASS_COLORS", {
    "long_haul": "#1F6FEB", "regional": "#D97706", "local": "#16A34A"})


def day_start(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def fit_view(lats, lons):
    clat, clon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    span = max(max(lats) - min(lats), max(lons) - min(lons), 0.02)
    return pdk.ViewState(latitude=clat, longitude=clon,
                         zoom=max(4.0, min(13.0, math.log2(360.0 / span) - 1)))


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

# --- load data ------------------------------------------------------------
places = db.q("SELECT place_id, label, lat, lon, needs_label FROM places")
if places.empty:
    empty_state("No places yet",
                "Place detection runs after the first enrichment pass. "
                "Run <code>python -m enrich.run</code> to populate the map.")
    st.stop()
P = {int(r.place_id): r for r in places.itertuples()}

journeys = db.q(
    "SELECT start_ts, origin_place_id, dest_place_id, distance_m, duration_s, fuel_l, "
    "is_local, journey_character FROM journeys WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts DESC",
    (from_ts, to_ts))

# --- trip-mix headline (all classes) --------------------------------------
counts = journeys["journey_character"].value_counts().to_dict() if not journeys.empty else {}
parts = [f"<b>{int(counts[c])}</b> {CLASS_LABELS[c]}"
         for c in ["long_haul", "regional", "local", "yard"] if counts.get(c, 0)]
st.markdown(f'<div class="tt-mix">This period: {" · ".join(parts)}</div>' if parts
            else '<div class="tt-mix">No trips this period.</div>', unsafe_allow_html=True)

# --- class filter ---------------------------------------------------------
choice = st.segmented_control("Class", list(FILTER_TO_CHAR), default="All", key="class_filter")
char = FILTER_TO_CHAR.get(choice or "All")

routes = journeys[journeys["is_local"] == 0]
fj = routes if char is None else routes[routes["journey_character"] == char]

# --- corridors from filtered journeys -------------------------------------
cpaths = {}
for r in db.q("SELECT place_a_id, place_b_id, path_geojson FROM corridors").itertuples():
    if r.path_geojson:
        cpaths[(int(r.place_a_id), int(r.place_b_id))] = json.loads(r.path_geojson)

agg = defaultdict(lambda: {"n": 0, "km": 0.0, "fuel": 0.0, "dur": 0, "last": None})
for j in fj.itertuples():
    if pd.isna(j.origin_place_id) or pd.isna(j.dest_place_id):
        continue
    a, b = int(j.origin_place_id), int(j.dest_place_id)
    if a == b:
        continue
    g = agg[(min(a, b), max(a, b))]
    g["n"] += 1
    g["km"] += (j.distance_m or 0) / 1000
    g["fuel"] += j.fuel_l or 0
    g["dur"] += j.duration_s or 0
    g["last"] = j.start_ts if g["last"] is None else max(g["last"], j.start_ts)

corr = []
for (a, b), g in agg.items():
    if a in P and b in P:
        corr.append({
            "key": f"{a}-{b}", "A": P[a].label, "B": P[b].label, "Trips": g["n"],
            "Distance": round(g["km"]), "Avg duration": round(g["dur"] / g["n"] / 3600, 1),
            "Avg fuel": round(g["fuel"] / g["n"]),
            "L/100km": round(g["fuel"] / g["km"] * 100, 1) if g["km"] else None,
            "last": theme.fmt_dt(g["last"], with_time=False),
            "path": cpaths.get((a, b)) or [[P[a].lon, P[a].lat], [P[b].lon, P[b].lat]]})
corr_df = pd.DataFrame(corr).sort_values(["Trips", "Distance"], ascending=False).reset_index(drop=True) \
    if corr else pd.DataFrame()

dwell = db.q("SELECT place_id, SUM(duration_s) dwell, COUNT(*) visits, MAX(ts) last_ts "
             "FROM place_visits WHERE ts BETWEEN ? AND ? GROUP BY place_id", (from_ts, to_ts))
places_df = pd.DataFrame([
    {"place_id": int(r.place_id), "label": P[int(r.place_id)].label, "lat": P[int(r.place_id)].lat,
     "lon": P[int(r.place_id)].lon, "dwell_s": int(r.dwell or 0), "visits": int(r.visits or 0),
     "last_ts": int(r.last_ts or 0)}
    for r in dwell.itertuples() if int(r.place_id) in P]) if not dwell.empty else pd.DataFrame()
if not places_df.empty:
    places_df = places_df.sort_values("dwell_s", ascending=False).reset_index(drop=True)

# --- period summary (respects the class filter) ---------------------------
span = to_ts - from_ts


def route_stats(lo, hi, character):
    cond, params = "", [lo, hi]
    if character:
        cond, params = " AND journey_character=?", [lo, hi, character]
    j = db.q("SELECT distance_m, start_ts, origin_place_id, dest_place_id FROM journeys "
             f"WHERE is_local=0 AND start_ts BETWEEN ? AND ?{cond}", tuple(params))
    if j.empty:
        return {"journeys": 0, "km": 0, "days": 0, "places": 0}
    days = len({datetime.fromtimestamp(t, timezone.utc).date() for t in j["start_ts"]})
    pl = set(j["origin_place_id"].dropna()) | set(j["dest_place_id"].dropna())
    return {"journeys": len(j), "km": j["distance_m"].sum() / 1000, "days": days, "places": len(pl)}


cur, prev = route_stats(from_ts, to_ts, char), route_stats(from_ts - span, from_ts, char)
has_prev = db.scalar("SELECT COUNT(*) FROM journeys WHERE start_ts < ?", (from_ts,), 0) > 0
longest = (fj.sort_values("distance_m", ascending=False).iloc[0] if not fj.empty else None)


def d(a, b):
    return round(a - b) if has_prev else None


s1, s2, s3, s4, s5 = st.columns(5)
with s1:
    metric_card("Active days", cur["days"], delta=d(cur["days"], prev["days"]))
with s2:
    metric_card("Route trips", cur["journeys"], delta=d(cur["journeys"], prev["journeys"]))
with s3:
    metric_card("Route distance", f"{cur['km']:,.0f}", "km", delta=d(cur["km"], prev["km"]))
with s4:
    metric_card("Places visited", cur["places"], delta=d(cur["places"], prev["places"]))
with s5:
    metric_card("Longest trip", f"{longest.distance_m / 1000:,.0f}" if longest is not None else "—",
                "km", hint=theme.fmt_dt(longest.start_ts, False) if longest is not None else None)

# --- cost row (whole period; not class-filtered) --------------------------
filled = db.scalar("SELECT COALESCE(SUM(volume_l),0) FROM fillings WHERE ts BETWEEN ? AND ?",
                   (from_ts, to_ts), 0) or 0
diesel = config.RATES["diesel_kes_per_l"]
km_rates = {c: config.RATES[f"{c}_kes_per_km"] for c in ROUTE_CLASSES}
all_routes = [(r.journey_character, r.distance_m) for r in routes.itertuples()]

st.markdown('<div style="height:.5rem"></div>', unsafe_allow_html=True)
ccols = st.columns(5)
with ccols[0]:
    metric_card("Fuel bought", format_kes(estimate.fuel_cost(filled, diesel)),
                hint=f"at KES {diesel}/L pump price")
if any(v is not None for v in km_rates.values()):
    total, _, incl, excl = estimate.revenue_by_class(all_routes, km_rates)
    foot = "Includes: " + ", ".join(CLASS_LABELS[c] for c in incl)
    if excl:
        foot += " · Excludes: " + ", ".join(CLASS_LABELS[c] for c in excl) + " (no rate)"
    with ccols[1]:
        metric_card("Est. revenue", format_kes(total), hint=foot)

# --- what-if rate calculator ----------------------------------------------
with st.expander("What-if rate calculator"):
    st.markdown("Enter hypothetical rates per kilometre to see what this period "
                "would be worth.")
    w = st.columns(3)
    inputs = {}
    for col, c in zip(w, ROUTE_CLASSES):
        inputs[c] = col.number_input(f"{CLASS_LABELS[c].title()} KES/km",
                                     value=km_rates[c], min_value=0.0, step=5.0, key=f"wi_{c}")
        if inputs[c] is None:
            col.caption("e.g. 95")
    if st.button("Calculate", type="primary"):
        total, breakdown, incl, _ = estimate.revenue_by_class(all_routes,
                                                              {c: inputs[c] for c in ROUTE_CLASSES})
        st.session_state["whatif"] = (total, breakdown, incl)
    if st.session_state.get("whatif"):
        total, breakdown, incl = st.session_state["whatif"]
        for c in incl:
            b = breakdown[c]
            st.markdown(f"{CLASS_LABELS[c].title()}: {b['km']:,.0f} km × "
                        f"KES {b['rate']:,.0f} = **{format_kes(b['kes'])}**")
        st.markdown(f"**Total: {format_kes(total)}**")
        st.caption("What-if calculation. Not stored. Not an actual estimate.")

# --- weekly activity strip ------------------------------------------------
if not fj.empty:
    with st.container(border=True):
        present = [c for c in ROUTE_CLASSES if (fj["journey_character"] == c).any()]
        legend = " ".join(
            f'<span><span class="dot" style="background:{TRIP_CLASS_COLORS[c]}"></span>'
            f'{CLASS_LABELS[c]}</span>' for c in present)
        st.markdown(f'<div class="tt-legend">{legend}</div>', unsafe_allow_html=True)

        monthly = span / 604800 > 12

        def bucket(ts):
            dt = datetime.fromtimestamp(ts, timezone.utc)
            return dt.strftime("%b %Y") if monthly else (dt - timedelta(days=dt.weekday())).strftime("%d %b")

        strip = fj.copy()
        strip["bucket"] = strip["start_ts"].apply(bucket)
        strip["Class"] = strip["journey_character"].map(CLASS_LABELS)
        g = strip.groupby(["bucket", "Class"]).size().reset_index(name="trips")
        fig = px.bar(g, x="bucket", y="trips", color="Class",
                     color_discrete_map={CLASS_LABELS[c]: TRIP_CLASS_COLORS[c] for c in ROUTE_CLASSES})
        fig.update_layout(height=110, margin=dict(l=0, r=0, t=2, b=2), showlegend=False,
                          hovermode="x unified", bargap=0.35, xaxis_title=None, yaxis_title=None,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          font=dict(family=theme.FONT, size=11, color=theme.MUTED))
        fig.update_yaxes(visible=False)
        fig.update_xaxes(showgrid=False, tickfont=dict(color=theme.MUTED, size=11), automargin=True)
        fig.update_traces(hovertemplate="%{fullData.name}: %{y} trips<extra></extra>")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

map_slot = st.container()

# --- Top routes / Top places (selectable) ---------------------------------
st.session_state.setdefault("sel_nonce", 0)
nonce = st.session_state.sel_nonce
sel_corridor, sel_place = None, None
left, right = st.columns(2)
with left:
    st.subheader("Top routes")
    if corr_df.empty:
        empty_state("No routes for this selection")
    else:
        show = corr_df.head(5).assign(Route=lambda x: x["A"] + " – " + x["B"])
        ev = st.dataframe(
            show[["Route", "Trips", "Distance", "Avg duration", "Avg fuel", "L/100km"]],
            hide_index=True, use_container_width=True, on_select="rerun",
            selection_mode="single-row", key=f"routes_{nonce}",
            column_config={
                "Distance": st.column_config.NumberColumn("Distance (km)", format="%d"),
                "Avg duration": st.column_config.NumberColumn("Avg duration (h)", format="%.1f"),
                "Avg fuel": st.column_config.NumberColumn("Avg fuel (L)", format="%d"),
                "L/100km": st.column_config.NumberColumn("L/100km", format="%.1f")})
        if ev.selection.rows:
            sel_corridor = show.iloc[ev.selection.rows[0]]["key"]
with right:
    st.subheader("Top places")
    if places_df.empty:
        empty_state("No places visited in this period")
    else:
        show = places_df.head(5).copy()
        show["Time there"] = show["dwell_s"].apply(theme.fmt_dur)
        show["Last visited"] = show["last_ts"].apply(relative_day)
        ev = st.dataframe(
            show[["label", "Time there", "visits", "Last visited"]], hide_index=True,
            use_container_width=True, on_select="rerun", selection_mode="single-row",
            key=f"places_{nonce}",
            column_config={"label": "Place", "visits": st.column_config.NumberColumn("Visits")})
        if ev.selection.rows:
            sel_place = int(show.iloc[ev.selection.rows[0]]["place_id"])

if (sel_corridor or sel_place is not None) and st.button("Clear selection"):
    st.session_state.sel_nonce += 1
    st.rerun()

# --- needs-label callout --------------------------------------------------
unlabeled = db.q("SELECT label, ROUND(lat,5) lat, ROUND(lon,5) lon FROM places WHERE needs_label=1")
if not unlabeled.empty:
    with st.expander(f"{len(unlabeled)} place(s) need a better name — edit places.yaml"):
        st.dataframe(unlabeled.rename(columns={"label": "Current name", "lat": "Lat", "lon": "Lon"}),
                     hide_index=True, use_container_width=True)
        pyaml = ROOT / "places.yaml"
        st.code(pyaml.read_text() if pyaml.exists()
                else "- label: Athi River yard\n  lat: -1.437\n  lon: 36.961\n", language="yaml")

# --- render the map into the top slot --------------------------------------
with map_slot:
    if fj.empty:
        empty_state(f"No {CLASS_LABELS.get(char, 'route')} trips in this period.")
    else:
        layers = []
        if not corr_df.empty:
            m = corr_df.copy()
            base_w = m["Trips"].clip(lower=1).add(1).clip(upper=8)
            m["width"] = [min(12, w * 1.5) if k == sel_corridor else w
                          for w, k in zip(base_w, m["key"])]
            m["color"] = ([theme.CORRIDOR_RGB + [180]] * len(m) if sel_corridor is None
                          else [theme.CORRIDOR_RGB + ([255] if k == sel_corridor else [76])
                                for k in m["key"]])
            m["name"] = (m["A"] + " – " + m["B"] + " · " + m["Trips"].astype(str) + " trips · "
                         + m["Distance"].astype(str) + " km")
            layers.append(pdk.Layer(
                "PathLayer", data=m, get_path="path", get_color="color", get_width="width",
                width_units="pixels", width_min_pixels=2, width_max_pixels=12,
                pickable=True, cap_rounded=True, joint_rounded=True))
        if not places_df.empty:
            pl = places_df.copy()
            base_r = (pl["dwell_s"].clip(lower=1) ** 0.5 * 40).clip(lower=200)
            pl["radius"] = [r * 1.5 if pid == sel_place else r for r, pid in zip(base_r, pl["place_id"])]
            alpha = [255 if pid == sel_place else 70 for pid in pl["place_id"]] \
                if sel_place is not None else [200] * len(pl)
            pl["fill"] = [theme.PLACE_RGB + [a] for a in alpha]
            pl["name"] = pl["label"] + " · " + pl["dwell_s"].apply(theme.fmt_dur)
            layers.append(pdk.Layer(
                "ScatterplotLayer", data=pl, get_position=["lon", "lat"], get_radius="radius",
                get_fill_color="fill", radius_min_pixels=5, radius_max_pixels=30, pickable=True,
                stroked=True, get_line_color=[255, 255, 255, 230], line_width_min_pixels=1))
            # readable place names directly on the map (no hover needed)
            layers.append(pdk.Layer(
                "TextLayer", data=pl, get_position=["lon", "lat"], get_text="label",
                get_size=13, size_units="pixels", get_color=[15, 23, 42],
                get_pixel_offset=[0, -16], get_text_anchor="'middle'",
                get_alignment_baseline="'bottom'", background=True,
                get_background_color=[255, 255, 255, 210]))

        if sel_corridor and not corr_df.empty:
            path = corr_df.loc[corr_df["key"] == sel_corridor, "path"].iloc[0]
            view = fit_view([p[1] for p in path], [p[0] for p in path])
        elif sel_place is not None and sel_place in P:
            view = pdk.ViewState(latitude=P[sel_place].lat, longitude=P[sel_place].lon, zoom=12)
        elif not places_df.empty:
            view = pdk.ViewState(latitude=float(places_df["lat"].mean()),
                                 longitude=float(places_df["lon"].mean()), zoom=6)
        else:
            view = fit_view([P[k].lat for k in P], [P[k].lon for k in P])

        st.pydeck_chart(pdk.Deck(
            layers=layers, initial_view_state=view, map_style=theme.MAP_STYLE,
            tooltip={"html": "<b>{name}</b>",
                     "style": {"backgroundColor": theme.INK, "color": "white",
                               "fontSize": "12px", "borderRadius": "8px"}}))
        st.caption("Blue lines: routes (thicker = more trips). Dark bubbles: places "
                   "(bigger = more time). The journey ledger is on the Audit Export page.")
