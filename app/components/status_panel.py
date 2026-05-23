"""The Status section: gather the flagged items and render them (or the empty state).

Surfaces only signals that already exist with no new computation — hard-safety
driver events, the four anomaly rules, and service-due — so it never fabricates a
status. The owner opens the Overview to learn "is anything wrong?"; this answers it.
"""

import streamlit as st

from app.components import db, status_item

_ANOM_TITLE = {
    "fuel_drop": "Possible fuel loss",
    "unusual_fill": "Unusual fuel fill",
    "consumption_drift": "Fuel economy drifting",
    "device_silent": "Tracker went silent",
}


def gather(frm, to):
    """Return the list of flagged items for the period (most severe first-ish)."""
    items = []
    hard = db.scalar("SELECT COUNT(*) FROM eco_flags WHERE hard_safety=1 AND ts BETWEEN ? AND ?",
                     (frm, to), 0) or 0
    if hard:
        items.append({
            "severity": "critical",
            "title": f"{int(hard)} hard-safety driver event{'s' if hard != 1 else ''}",
            "evidence": "Extreme-severity events — review on the Driver page.",
            "page": "pages/3_Driver.py", "confidence": "observed"})
    for r in db.q("SELECT type, severity, detail FROM anomalies WHERE ts BETWEEN ? AND ? "
                  "ORDER BY ts DESC", (frm, to)).itertuples():
        sev = "critical" if str(r.severity or "").lower() == "high" else "warn"
        items.append({
            "severity": sev, "title": _ANOM_TITLE.get(r.type, r.type),
            "evidence": r.detail or "", "page": "pages/6_Anomalies.py", "confidence": "inferred"})
    due = db.q("SELECT service_type FROM service_status WHERE due=1")
    if not due.empty:
        names = ", ".join(s.replace("_", " ") for s in due["service_type"])
        items.append({
            "severity": "warn", "title": f"Service due: {names}",
            "evidence": "Generic FAW intervals off a 0 km baseline — confirm against the "
                        "truck's real service history.",
            "page": "pages/5_Maintenance.py", "confidence": "inferred"})
    return items


def render(items):
    st.markdown('<div class="tt-h2">Status</div>'
                '<div class="tt-small" style="margin:-.1rem 0 .6rem">Anything worth your '
                'attention this period.</div>', unsafe_allow_html=True)
    if not items:
        st.markdown(
            '<div class="tt-card" style="border-left:3px solid var(--ok)">'
            '<b style="color:var(--ok)">✓ Nothing flagged.</b> '
            '<span class="tt-small">Truck operating normally.</span></div>',
            unsafe_allow_html=True)
        return
    for it in items:
        status_item.render(it)
