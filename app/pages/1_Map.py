"""Map — where has KDX 415X been: routes, parkings, and stops."""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402

theme.page_setup("Map")

# getattr default guards against Streamlit Cloud serving a stale (cached)
# config module right after a redeploy adds a new attribute.
STOP_MIN = getattr(config, "STOP_MIN_DISPLAY_S", 180)

frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Map", f"{label} · routes driven, where it parked and stopped")

trips = db.q(
    "SELECT start_ts, end_ts, start_lat, start_lon, end_lat, end_lon, distance_m "
    "FROM trips WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts", (frm, to))
if trips.empty:
    empty_state("No trips to map", "Pick a wider period in the sidebar.")
    st.stop()

pos = db.q("SELECT ts, lat, lon FROM positions WHERE ts BETWEEN ? AND ? ORDER BY ts", (frm, to))

# --- one path per trip: real GPS track where we have it, else a straight line
paths = []
for t in trips.itertuples():
    seg = pos[(pos.ts >= t.start_ts) & (pos.ts <= t.end_ts)] if not pos.empty else pos
    if len(seg) >= 2:
        path = seg[["lon", "lat"]].values.tolist()
    elif t.start_lat is not None and t.end_lat is not None:
        path = [[t.start_lon, t.start_lat], [t.end_lon, t.end_lat]]
    else:
        continue
    paths.append({"path": path, "name": f"{(t.distance_m or 0) / 1000:.1f} km trip"})

layers = []
if paths:
    layers.append(pdk.Layer(
        "PathLayer", data=pd.DataFrame(paths), get_path="path",
        get_color=theme.ACCENT_RGB + [200], width_min_pixels=3, get_width=4,
        pickable=True, cap_rounded=True, joint_rounded=True))

# --- parkings: radius by duration
parks = db.q(
    "SELECT start_ts, end_ts, duration_s, lat, lon, location FROM parkings "
    "WHERE start_ts BETWEEN ? AND ? AND lat IS NOT NULL", (frm, to))
if not parks.empty:
    hours = (parks["duration_s"].fillna(0) / 3600).clip(lower=0.1)
    parks["r"] = hours.pow(0.5) * 220
    parks["name"] = (parks["location"].fillna("Parking") + " · parked "
                     + parks["duration_s"].apply(theme.fmt_dur)
                     + " (" + parks["start_ts"].apply(lambda s: theme.fmt_dt(s)) + ")")
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=parks, get_position=["lon", "lat"], get_radius="r",
        get_fill_color=[60, 90, 120, 170], pickable=True, stroked=True,
        get_line_color=[255, 255, 255, 220], line_width_min_pixels=1))

# --- stops: only non-trivial ones
stps = db.q(
    "SELECT start_ts, duration_s, lat, lon, location FROM stops "
    "WHERE start_ts BETWEEN ? AND ? AND duration_s >= ? AND lat IS NOT NULL",
    (frm, to, STOP_MIN))
if not stps.empty:
    stps["name"] = (stps["location"].fillna("Stop") + " · stopped "
                    + stps["duration_s"].apply(theme.fmt_dur))
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=stps, get_position=["lon", "lat"], get_radius=120,
        get_fill_color=[200, 80, 30, 150], pickable=True))

center_lat = float(pd.concat([trips.start_lat, trips.end_lat]).mean())
center_lon = float(pd.concat([trips.start_lon, trips.end_lon]).mean())
st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=6),
    map_style=theme.MAP_STYLE,
    tooltip={"html": "<b>{name}</b>",
             "style": {"backgroundColor": theme.INK, "color": "white",
                       "fontSize": "12px", "borderRadius": "8px"}}))

st.caption("Orange line: route driven. Blue circles: parkings (size = how long). "
           "Orange dots: stops over "
           f"{STOP_MIN // 60} min.")

# --- parkings & stops tables ---------------------------------------------
st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Parkings")
if parks.empty:
    empty_state("No parkings in this period")
else:
    pt = pd.DataFrame({
        "Location": parks["location"],
        "Arrived": pd.to_datetime(parks["start_ts"], unit="s", utc=True),
        "Left": pd.to_datetime(parks["end_ts"], unit="s", utc=True),
        "Duration": parks["duration_s"].apply(theme.fmt_dur),
    }).sort_values("Arrived", ascending=False)
    st.dataframe(pt, hide_index=True, use_container_width=True, column_config={
        "Arrived": st.column_config.DatetimeColumn("Arrived", format="DD MMM, HH:mm"),
        "Left": st.column_config.DatetimeColumn("Left", format="DD MMM, HH:mm")})

st.subheader("Stops")
if stps.empty:
    empty_state("No notable stops in this period",
                f"Only stops longer than {STOP_MIN // 60} minutes are shown.")
else:
    sttab = pd.DataFrame({
        "Location": stps["location"],
        "When": pd.to_datetime(stps["start_ts"], unit="s", utc=True),
        "Duration": stps["duration_s"].apply(theme.fmt_dur),
    }).sort_values("When", ascending=False)
    st.dataframe(sttab, hide_index=True, use_container_width=True, column_config={
        "When": st.column_config.DatetimeColumn("When", format="DD MMM, HH:mm")})
