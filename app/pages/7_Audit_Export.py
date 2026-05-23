"""Audit Export — the journey ledger to check a Genwatt statement line by line."""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402

theme.page_setup("Audit Export")
frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Audit Export", f"{label} · every journey, to verify a statement line by line")

P = {int(r.place_id): r.label for r in db.q("SELECT place_id, label FROM places").itertuples()}


def fname(prefix):
    return (f"KDX415X_{prefix}_{theme.fmt_dt(frm, False).replace(' ', '')}_"
            f"{theme.fmt_dt(to, False).replace(' ', '')}.csv")


journeys = db.q(
    "SELECT start_ts, end_ts, origin_place_id, dest_place_id, leg_count, distance_m, "
    "duration_s, fuel_l, is_local FROM journeys WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts DESC",
    (frm, to))

if journeys.empty:
    empty_state("No journeys in this period", "Pick a wider period in the sidebar.")
    st.stop()

# Round trips (jobs) — the owner's unit of work, above the per-journey ledger.
import json as _json  # noqa: E402

rt = db.q("SELECT start_ts, end_ts, primary_destination_name dest, journey_class cls, "
          "total_distance_km km, total_duration_s dur, constituent_journey_ids cj "
          "FROM round_trips WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts DESC", (frm, to))
if not rt.empty:
    st.subheader("Round trips (jobs)")
    rtl = pd.DataFrame({
        "Start": theme.local_series(rt["start_ts"]),
        "End": theme.local_series(rt["end_ts"]),
        "Destination": rt["dest"],
        "Class": rt["cls"],
        "Distance (km)": rt["km"].round(0),
        "Duration (h)": (rt["dur"] / 3600).round(1),
        "Trips": rt["cj"].map(lambda s: len(_json.loads(s))),
    })
    st.dataframe(rtl, hide_index=True, width="stretch", column_config={
        "Start": st.column_config.DatetimeColumn("Start", format="DD MMM YYYY, HH:mm"),
        "End": st.column_config.DatetimeColumn("End", format="DD MMM YYYY, HH:mm")})
    st.download_button("Download round-trips CSV", data=rtl.to_csv(index=False).encode("utf-8"),
                       file_name=fname("round-trips"), mime="text/csv")
    st.markdown('<hr/>', unsafe_allow_html=True)


def lbl(pid):
    return P.get(int(pid), "—") if not pd.isna(pid) else "—"


ledger = pd.DataFrame({
    "Date": theme.local_series(journeys["start_ts"]),
    "From": journeys["origin_place_id"].apply(lbl),
    "To": journeys["dest_place_id"].apply(lbl),
    "Legs": journeys["leg_count"],
    "Distance (km)": (journeys["distance_m"] / 1000).round(0),
    "Duration (h)": (journeys["duration_s"] / 3600).round(1),
    "Fuel (L)": journeys["fuel_l"].round(0),
    "Type": journeys["is_local"].map({1: "local", 0: "route"}),
})
routes = ledger[ledger["Type"] == "route"]

c1, c2, c3 = st.columns(3)
c1.metric("Route journeys", f"{len(routes)}")
c2.metric("Route distance", f"{routes['Distance (km)'].sum():,.0f} km")
c3.metric("Total fuel", f"{ledger['Fuel (L)'].sum():,.0f} L")

st.markdown('<hr/>', unsafe_allow_html=True)
st.dataframe(ledger, hide_index=True, width="stretch", column_config={
    "Date": st.column_config.DatetimeColumn("Date", format="DD MMM YYYY, HH:mm")})
st.download_button("Download journeys CSV", data=ledger.to_csv(index=False).encode("utf-8"),
                   file_name=fname("journeys"), mime="text/csv")

with st.expander("All trips in this period (raw legs)"):
    trips = db.q(
        "SELECT start_ts, end_ts, distance_m, duration_s, avg_speed_kmh, max_speed_kmh, "
        "consumed_l FROM trips WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts DESC", (frm, to))
    if trips.empty:
        empty_state("No trips in this period")
    else:
        tl = pd.DataFrame({
            "Start": theme.local_series(trips["start_ts"]),
            "End": theme.local_series(trips["end_ts"]),
            "Distance (km)": (trips["distance_m"] / 1000).round(1),
            "Duration (h)": (trips["duration_s"] / 3600).round(2),
            "Avg (km/h)": trips["avg_speed_kmh"],
            "Max (km/h)": trips["max_speed_kmh"],
            "Fuel (L)": trips["consumed_l"].round(2),
        })
        st.dataframe(tl, hide_index=True, width="stretch", column_config={
            "Start": st.column_config.DatetimeColumn("Start", format="DD MMM, HH:mm"),
            "End": st.column_config.DatetimeColumn("End", format="DD MMM, HH:mm")})
        st.download_button("Download trips CSV", data=tl.to_csv(index=False).encode("utf-8"),
                           file_name=fname("trips"), mime="text/csv")
