"""Driver — how is the driver behaving?"""

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

theme.page_setup("Driver")
frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Driver", f"{label} · harsh events, speeding, and the weekly score")

TYPE_LABELS = {"harsh_accel": "Harsh acceleration", "harsh_brake": "Harsh braking",
               "harsh_corner": "Harsh cornering", "speeding": "Speeding", "idling": "Idling",
               "other": "Other"}

score = db.scalar("SELECT score FROM driver_score ORDER BY period_start DESC LIMIT 1")
events = db.q("SELECT ts, type, value FROM eco_events WHERE ts BETWEEN ? AND ?", (frm, to))
total = len(events)
worst = (events["type"].map(TYPE_LABELS).value_counts().idxmax() if total else "—")

cards_row([
    dict(label="Driver score", value=f"{score:.0f}" if score is not None else "—",
         unit="/100", hint="latest week · higher is better"),
    dict(label="Events", value=f"{total}", unit="", hint="this period"),
    dict(label="Most common", value=worst, unit=""),
])

st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Weekly score")
weeks = db.q("SELECT period_start, score FROM driver_score ORDER BY period_start")
if weeks.empty:
    empty_state("No score yet", "The score appears once eco-driving events are recorded.")
else:
    weeks["week"] = pd.to_datetime(weeks["period_start"], unit="s", utc=True)
    fig = px.line(weeks, x="week", y="score", markers=True)
    fig.update_traces(line_color=theme.ACCENT,
                      hovertemplate="week of %{x|%d %b}<br>score %{y:.0f}<extra></extra>")
    fig.update_yaxes(range=[0, 100], title=None)
    fig.update_xaxes(title=None)
    st.plotly_chart(theme.style_fig(fig, height=240), use_container_width=True)

st.subheader("Event breakdown")
if not total:
    empty_state("No events in this period",
                "Eco Driving is configured on the device; events will appear here as they occur.")
else:
    counts = events["type"].map(lambda t: TYPE_LABELS.get(t, t)).value_counts().reset_index()
    counts.columns = ["type", "count"]
    fig = px.bar(counts, x="count", y="type", orientation="h")
    fig.update_traces(marker_color=theme.ACCENT,
                      hovertemplate="%{y}<br>%{x} events<extra></extra>")
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None)
    st.plotly_chart(theme.style_fig(fig, height=260), use_container_width=True)
