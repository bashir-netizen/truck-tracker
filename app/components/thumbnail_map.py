"""A small, non-interactive corridor preview that links to the full Map page.

Reuses the token-free Carto basemap and the corridors' cached paths; renders
compact, then a page link hands off to the full interactive Map.
"""

import math

import pydeck as pdk
import streamlit as st

from app.components import theme


def render(corridor_paths, place_points, height=200):
    """corridor_paths: list of [[lon,lat],…]; place_points: list of (lon, lat)."""
    layers = []
    if corridor_paths:
        layers.append(pdk.Layer(
            "PathLayer", data=[{"path": p} for p in corridor_paths], get_path="path",
            get_color=theme.hex_to_rgb(theme.ACCENT) + [170], get_width=3,
            width_units="pixels", width_min_pixels=2))
    if place_points:
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=[{"lon": lo, "lat": la} for lo, la in place_points],
            get_position=["lon", "lat"], get_radius=320, radius_min_pixels=3,
            get_fill_color=theme.PLACE_RGB + [200]))

    pts = [pt for p in corridor_paths for pt in p] + [[lo, la] for lo, la in place_points]
    if pts:
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        clat, clon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
        span = max(max(lats) - min(lats), max(lons) - min(lons), 0.05)
        view = pdk.ViewState(latitude=clat, longitude=clon,
                             zoom=max(4.0, min(11.0, math.log2(360 / span) - 1.5)))
    else:
        view = pdk.ViewState(latitude=0.5, longitude=37.5, zoom=5)   # Kenya

    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view,
                             map_style=theme.MAP_STYLE, height=height),
                    width="stretch")
    st.page_link("pages/1_Map.py", label="Open full map →")
