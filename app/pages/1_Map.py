"""Map — where has KDX 415X been?"""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402

from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402

theme.page_setup("Map")
frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Map", f"{label} · routes and the places visited most")

trips = db.q(
    "SELECT start_ts, start_lat, start_lon, end_lat, end_lon, distance_m, duration_s "
    "FROM trips WHERE start_ts BETWEEN ? AND ? "
    "AND start_lat IS NOT NULL AND end_lat IS NOT NULL", (frm, to))

if trips.empty:
    empty_state("No trips to map", "Pick a wider period in the sidebar.")
    st.stop()

trips["km"] = (trips["distance_m"] / 1000).round(1)
trips["name"] = trips["km"].astype(str) + " km trip"

layers = [pdk.Layer(
    "LineLayer", data=trips,
    get_source_position=["start_lon", "start_lat"],
    get_target_position=["end_lon", "end_lat"],
    get_color=theme.ACCENT_RGB + [150], get_width=2, pickable=True)]

places = db.q("SELECT label, lat, lon, visit_count FROM places")
if not places.empty:
    places["label"] = places["label"].fillna("Unlabelled place")
    places["name"] = places["label"] + " · " + places["visit_count"].astype(str) + " visits"
    places["r"] = places["visit_count"].clip(lower=1) ** 0.5 * 90
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=places,
        get_position=["lon", "lat"], get_radius="r",
        get_fill_color=[27, 26, 23, 170], pickable=True, stroked=True,
        get_line_color=[255, 255, 255, 220], line_width_min_pixels=1))

center_lat = float(pd.concat([trips.start_lat, trips.end_lat]).mean())
center_lon = float(pd.concat([trips.start_lon, trips.end_lon]).mean())

st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=6),
    map_style=theme.MAP_STYLE,
    tooltip={"html": "<b>{name}</b>",
             "style": {"backgroundColor": theme.INK, "color": "white",
                       "fontSize": "12px", "borderRadius": "8px"}}))

st.subheader("Most-visited places")
if places.empty:
    empty_state("No repeat places yet",
                "Places appear once the truck visits the same spot a few times. "
                "Label them by copying <code>places.yaml.example</code> to "
                "<code>places.yaml</code>.")
else:
    show = places[["label", "visit_count"]].sort_values("visit_count", ascending=False)
    st.dataframe(show, hide_index=True, use_container_width=True,
                 column_config={"label": "Place",
                                "visit_count": st.column_config.NumberColumn("Visits")})
