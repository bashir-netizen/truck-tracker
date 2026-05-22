"""Utilization — how hard is the asset working?"""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.metric_card import cards_row  # noqa: E402

theme.page_setup("Utilization")
frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Utilization", f"{label} · how much the truck is being used")

agg = db.q(
    "SELECT COUNT(*) AS trips, COALESCE(SUM(distance_m),0) AS dist, "
    "COALESCE(SUM(duration_s),0) AS dur, COALESCE(MAX(distance_m),0) AS longest, "
    "COUNT(DISTINCT strftime('%Y-%m-%d', start_ts,'unixepoch')) AS days "
    "FROM trips WHERE start_ts BETWEEN ? AND ?", (frm, to)).iloc[0]

if not agg["trips"]:
    empty_state("No trips in this period", "Pick a wider period in the sidebar.")
    st.stop()

drive_h = agg["dur"] / 3600.0
avg_km = (agg["dist"] / 1000.0) / agg["trips"]
cards_row([
    dict(label="Active days", value=f"{int(agg['days'])}", unit=""),
    dict(label="Driving time", value=f"{drive_h:,.0f}", unit="h"),
    dict(label="Avg trip", value=f"{avg_km:,.0f}", unit="km"),
])
st.markdown('<div style="height:.7rem"></div>', unsafe_allow_html=True)
cards_row([
    dict(label="Trips", value=f"{int(agg['trips'])}", unit=""),
    dict(label="Longest trip", value=f"{agg['longest']/1000:,.0f}", unit="km"),
    dict(label="Distance", value=f"{agg['dist']/1000:,.0f}", unit="km"),
])

st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Trips per day")
perday = db.q(
    "SELECT strftime('%Y-%m-%d', start_ts,'unixepoch') AS day, COUNT(*) AS trips, "
    "SUM(distance_m)/1000.0 AS km FROM trips WHERE start_ts BETWEEN ? AND ? "
    "GROUP BY day ORDER BY day", (frm, to))
perday["day"] = pd.to_datetime(perday["day"], utc=True)
fig = px.bar(perday, x="day", y="trips")
fig.update_traces(marker_color=theme.ACCENT,
                  hovertemplate="%{x|%d %b}<br>%{y} trips<extra></extra>")
fig.update_xaxes(title=None)
fig.update_yaxes(title=None)
st.plotly_chart(theme.style_fig(fig, height=260), use_container_width=True)
