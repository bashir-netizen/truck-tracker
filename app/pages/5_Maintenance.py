"""Maintenance — what service is due?"""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402

theme.page_setup("Maintenance")
theme.freshness_caption()
theme.header("Maintenance", "Service due, driven by actual distance")

st.markdown(
    '<div style="background:#FFFFFF;border:1px solid #E5E7EB;border-left:3px solid #c47d1d;'
    'border-radius:8px;padding:.65rem .9rem;margin:0 0 1.1rem;font-size:.9rem;color:#0F172A">'
    '<span style="display:inline-block;font-size:.64rem;font-weight:700;letter-spacing:.06em;'
    'text-transform:uppercase;color:#c47d1d;border:1px solid #c47d1d;border-radius:999px;'
    'padding:.03rem .45rem;margin-right:.5rem">Inferred</span>'
    'Service intervals shown are <b>generic FAW defaults</b> calculated from a 0 km '
    'baseline — <b>not</b> the truck’s actual service history. Update '
    '<code>services.yaml</code> with real last-service data, or ingest Wialon Maintenance '
    'when configured.</div>',
    unsafe_allow_html=True)

NAMES = {"engine_oil": "Engine oil", "transmission": "Transmission",
         "air_filter": "Air filter", "major_service": "Major service"}

svc = db.q(
    "SELECT service_type, interval_km, current_odometer_m, last_service_odometer_m, "
    "km_remaining, due FROM service_status ORDER BY km_remaining")

odo = db.scalar("SELECT current_odometer_m FROM service_status LIMIT 1", default=0) or 0
st.markdown(
    f'<div class="tt-sub">Current odometer (from cumulative trip distance): '
    f'<b>{odo/1000:,.0f} km</b>. Engine-hours-based service is not tracked '
    f'(the hours counter is not configured in Wialon).</div>',
    unsafe_allow_html=True)
st.markdown('<hr/>', unsafe_allow_html=True)

if svc.empty:
    empty_state("No service schedule",
                "Define intervals in <code>config.py</code> and run "
                "<code>python -m enrich.run</code>.")
    st.stop()

for _, r in svc.iterrows():
    name = NAMES.get(r["service_type"], r["service_type"])
    interval = r["interval_km"] or 0
    used = max(0, (r["current_odometer_m"] - r["last_service_odometer_m"]) / 1000.0)
    remaining = r["km_remaining"]
    frac = min(1.0, used / interval) if interval else 0
    badge = ('<span class="tt-pill high">DUE NOW</span>' if r["due"]
             else f'<span class="tt-sub">{remaining:,.0f} km to go</span>')
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
        f'<b>{name}</b>{badge}</div>', unsafe_allow_html=True)
    st.progress(frac)
    st.caption(f"{used:,.0f} of {interval:,.0f} km since last service")
    st.markdown('<div style="height:.5rem"></div>', unsafe_allow_html=True)

st.caption("Record completed services in services.yaml (copy services.yaml.example) "
           "so the countdown resets from the right odometer.")
