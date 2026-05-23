"""Fuel — is the fuel adding up?"""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.metric_card import cards_row  # noqa: E402

theme.page_setup("Fuel")
frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Fuel", f"{label} · consumption, fills, and efficiency")

consumed = db.scalar("SELECT COALESCE(SUM(consumed_l),0) FROM trips "
                     "WHERE start_ts BETWEEN ? AND ?", (frm, to), default=0)
filled = db.scalar("SELECT COALESCE(SUM(volume_l),0) FROM fillings "
                   "WHERE ts BETWEEN ? AND ?", (frm, to), default=0)
dist = db.scalar("SELECT COALESCE(SUM(distance_m),0) FROM trips "
                 "WHERE start_ts BETWEEN ? AND ? AND distance_m>=?",
                 (frm, to, config.MIN_ECONOMY_KM * 1000), default=0)
fuel_eco = db.scalar("SELECT COALESCE(SUM(consumed_l),0) FROM trips "
                     "WHERE start_ts BETWEEN ? AND ? AND distance_m>=?",
                     (frm, to, config.MIN_ECONOMY_KM * 1000), default=0)
econ = (fuel_eco / (dist / 1000.0) * 100) if dist else 0

cards_row([
    dict(label="Consumed", value=f"{consumed:,.0f}", unit="L", confidence="inferred"),
    dict(label="Filled", value=f"{filled:,.0f}", unit="L", confidence="observed",
         hint=f"{db.scalar('SELECT COUNT(*) FROM fillings WHERE ts BETWEEN ? AND ?', (frm, to), default=0)} fills"),
    dict(label="Avg economy", value=f"{econ:.1f}", unit="L/100km", confidence="inferred"),
])

st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Economy per trip")
eco = db.q(
    "SELECT t.start_ts AS ts, m.l_per_100km AS l100 FROM trips t "
    "JOIN trip_metrics m ON m.unit_id=t.unit_id AND m.start_ts=t.start_ts "
    "WHERE t.start_ts BETWEEN ? AND ? AND m.l_per_100km IS NOT NULL "
    "ORDER BY t.start_ts", (frm, to))
if eco.empty:
    empty_state("No economy data", "Need trips over "
                f"{config.MIN_ECONOMY_KM} km to compute L/100km reliably.")
else:
    eco["when"] = pd.to_datetime(eco["ts"], unit="s", utc=True)
    fig = px.line(eco, x="when", y="l100", markers=True)
    fig.update_traces(line_color=theme.ACCENT,
                      hovertemplate="%{x|%d %b %H:%M}<br>%{y:.1f} L/100km<extra></extra>")
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None)
    st.plotly_chart(theme.style_fig(fig, height=260), width="stretch")

st.subheader("Fuel fillings")
fills = db.q(
    "SELECT ts, volume_l, level_before_l, level_after_l FROM fillings "
    "WHERE ts BETWEEN ? AND ? ORDER BY ts DESC", (frm, to))
if fills.empty:
    empty_state("No fillings in this period")
else:
    fills["When"] = pd.to_datetime(fills["ts"], unit="s", utc=True)
    st.dataframe(
        fills[["When", "volume_l", "level_before_l", "level_after_l"]],
        hide_index=True, width="stretch",
        column_config={
            "When": st.column_config.DatetimeColumn("When", format="DD MMM YYYY, HH:mm"),
            "volume_l": st.column_config.NumberColumn("Filled", format="%.1f L"),
            "level_before_l": st.column_config.NumberColumn("Before", format="%.1f L"),
            "level_after_l": st.column_config.NumberColumn("After", format="%.1f L"),
        })
