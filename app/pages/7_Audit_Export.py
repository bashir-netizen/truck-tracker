"""Audit Export — the ground-truth ledger to check statements against."""

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
theme.header("Audit Export",
             f"{label} · every trip, to verify a statement line by line")

trips = db.q(
    "SELECT start_ts, end_ts, distance_m, duration_s, avg_speed_kmh, max_speed_kmh, "
    "consumed_l FROM trips WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts", (frm, to))

if trips.empty:
    empty_state("No trips in this period", "Pick a wider period in the sidebar.")
    st.stop()

ledger = pd.DataFrame({
    "Start": pd.to_datetime(trips["start_ts"], unit="s", utc=True),
    "End": pd.to_datetime(trips["end_ts"], unit="s", utc=True),
    "Distance (km)": (trips["distance_m"] / 1000).round(1),
    "Duration (h)": (trips["duration_s"] / 3600).round(2),
    "Avg (km/h)": trips["avg_speed_kmh"],
    "Max (km/h)": trips["max_speed_kmh"],
    "Fuel (L)": trips["consumed_l"].round(2),
})

c1, c2, c3 = st.columns(3)
c1.metric("Trips", f"{len(ledger)}")
c2.metric("Total distance", f"{ledger['Distance (km)'].sum():,.0f} km")
c3.metric("Total fuel", f"{ledger['Fuel (L)'].sum():,.0f} L")

st.markdown('<hr/>', unsafe_allow_html=True)
st.dataframe(
    ledger, hide_index=True, use_container_width=True,
    column_config={
        "Start": st.column_config.DatetimeColumn("Start", format="DD MMM YYYY, HH:mm"),
        "End": st.column_config.DatetimeColumn("End", format="DD MMM YYYY, HH:mm"),
    })

csv = ledger.to_csv(index=False).encode("utf-8")
fname = (f"KDX415X_audit_"
         f"{theme.fmt_dt(frm, False).replace(' ', '')}_"
         f"{theme.fmt_dt(to, False).replace(' ', '')}.csv")
st.download_button("Download CSV ledger", data=csv, file_name=fname, mime="text/csv")
st.caption("PDF export and a scheduled weekly summary land in Stage 5.")
