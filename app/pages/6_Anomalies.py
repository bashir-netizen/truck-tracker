"""Anomalies — what looks wrong?"""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402

theme.page_setup("Anomalies")
frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Anomalies", f"{label} · fuel, consumption, and device-health flags")

NAMES = {"fuel_drop": "Possible fuel loss", "unusual_fill": "Unusual fill",
         "consumption_drift": "Consumption drift", "device_silent": "Device silent"}

rows = db.q(
    "SELECT ts, type, severity, detail FROM anomalies "
    "WHERE ts BETWEEN ? AND ? ORDER BY ts DESC", (frm, to))

if rows.empty:
    empty_state("No anomalies detected this period",
                "Fuel drops, oversized fills, consumption drift, and data gaps "
                "would appear here.")
    st.stop()

for _, r in rows.iterrows():
    sev = r["severity"] or "medium"
    name = NAMES.get(r["type"], r["type"])
    warn = "⚠ " if sev == "high" else ""
    st.markdown(
        f'<div class="tt-row"><div>{warn}<b>{name}</b>'
        f'<div class="tt-sub">{r["detail"]}</div></div>'
        f'<div style="text-align:right">'
        f'<span class="tt-pill {sev}">{sev.upper()}</span>'
        f'<div class="tt-sub">{theme.fmt_dt(r["ts"], with_time=False)}</div></div></div>',
        unsafe_allow_html=True)
