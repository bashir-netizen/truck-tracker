"""Overview — what did the truck do, at a glance?"""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.metric_card import cards_row  # noqa: E402

theme.page_setup("Overview")

if not db.has_data():
    theme.header("Overview")
    empty_state("No data yet",
                "Run <code>python -m ingest.run</code> then "
                "<code>python -m enrich.run</code> to populate the database.")
    st.stop()

frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Overview", f"{label} · independent record of what KDX 415X actually did")


def period_sum(col, table="trips", ts_col="start_ts", where="", lo=None, hi=None):
    lo, hi = (frm if lo is None else lo), (to if hi is None else hi)
    return db.scalar(
        f"SELECT COALESCE(SUM({col}),0) FROM {table} "
        f"WHERE {ts_col} BETWEEN ? AND ? {where}", (lo, hi), default=0) or 0


def economy(lo, hi):
    dist = db.scalar("SELECT COALESCE(SUM(distance_m),0) FROM trips "
                     "WHERE start_ts BETWEEN ? AND ? AND distance_m>=?",
                     (lo, hi, config.MIN_ECONOMY_KM * 1000), default=0) or 0
    fuel = db.scalar("SELECT COALESCE(SUM(consumed_l),0) FROM trips "
                     "WHERE start_ts BETWEEN ? AND ? AND distance_m>=?",
                     (lo, hi, config.MIN_ECONOMY_KM * 1000), default=0) or 0
    return (fuel / (dist / 1000.0) * 100) if dist else 0


span = to - frm
p_from, p_to = frm - span, frm  # previous equal-length window for deltas

dist_km = period_sum("distance_m") / 1000.0
prev_km = period_sum("distance_m", lo=p_from, hi=p_to) / 1000.0
trips_n = int(db.scalar(
    "SELECT COUNT(*) FROM trips WHERE start_ts BETWEEN ? AND ?", (frm, to), default=0) or 0)
fuel_l = period_sum("consumed_l")
econ = economy(frm, to)
prev_econ = economy(p_from, p_to)
score = db.scalar("SELECT score FROM driver_score ORDER BY period_start DESC LIMIT 1")
hard = db.scalar("SELECT COUNT(*) FROM eco_flags WHERE hard_safety=1 AND ts BETWEEN ? AND ?",
                 (frm, to), default=0) or 0
eco_total = db.scalar("SELECT COUNT(*) FROM eco_events WHERE ts BETWEEN ? AND ?",
                      (frm, to), default=0) or 0
eco_per100 = eco_total / (period_sum("distance_m") / 1000 / 100) if period_sum("distance_m") else 0
anomalies = db.scalar("SELECT COUNT(*) FROM anomalies WHERE ts BETWEEN ? AND ?",
                      (frm, to), default=0) or 0

cards_row([
    dict(label="Distance", value=f"{dist_km:,.0f}", unit="km",
         delta=round(dist_km - prev_km) if prev_km else None, hint="vs prev period"),
    dict(label="Trips", value=f"{trips_n}", unit=""),
    dict(label="Fuel consumed", value=f"{fuel_l:,.0f}", unit="L"),
])
st.markdown('<div style="height:.7rem"></div>', unsafe_allow_html=True)
cards_row([
    dict(label="Avg economy", value=f"{econ:.1f}", unit="L/100km",
         delta=round(econ - prev_econ, 1) if prev_econ else None,
         delta_good_up=False, hint="vs prev period"),
    dict(label="Hard safety events", value=f"{int(hard)}",
         tone="alert" if hard else None,
         hint="this period" if hard else "within normal range"),
    dict(label="Open anomalies", value=f"{int(anomalies)}", unit="",
         hint="this period" if anomalies else "none flagged"),
])
_score = f"{score:.1f}" if score is not None else "—"
st.caption(f"{int(eco_total)} driver events, mostly mild/medium · "
           f"{eco_per100:.1f} per 100 km · Wialon score {_score} (reference)")

st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Distance by day")
daily = db.q(
    "SELECT strftime('%Y-%m-%d', start_ts, 'unixepoch') AS day, "
    "       SUM(distance_m)/1000.0 AS km FROM trips "
    "WHERE start_ts BETWEEN ? AND ? GROUP BY day ORDER BY day", (frm, to))
if daily.empty:
    empty_state("No trips in this period", "Try a wider period in the sidebar.")
else:
    fig = px.bar(daily, x="day", y="km")
    fig.update_traces(marker_color=theme.ACCENT,
                      hovertemplate="%{x}<br>%{y:.0f} km<extra></extra>")
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)
    st.plotly_chart(theme.style_fig(fig, height=260), use_container_width=True)

st.caption("Use the pages in the sidebar for the map, fuel, driver, "
           "utilization, maintenance, anomalies, and the audit export.")
