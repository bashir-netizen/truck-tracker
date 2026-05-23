"""Driver — lead with what's actionable; Wialon's score is a reference only."""

import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from app.components import db, theme  # noqa: E402
from app.components.empty_state import empty_state  # noqa: E402
from app.components.metric_card import metric_card  # noqa: E402

theme.page_setup("Driver")
frm, to, label = theme.period_selector()
theme.freshness_caption()
theme.header("Driver", f"{label} · safety signals, patterns, and the Wialon reference")

TYPE_LABELS = {"harsh_accel": "Harsh acceleration", "harsh_brake": "Harsh braking",
               "harsh_corner": "Harsh cornering", "speeding": "Speeding", "idling": "Idling",
               "other": "Other"}
P = {int(r.place_id): r.label for r in db.q("SELECT place_id, label FROM places").itertuples()}

events = db.q("SELECT ts, type, value FROM eco_events WHERE ts BETWEEN ? AND ?", (frm, to))
total = len(events)
hard = db.scalar("SELECT COUNT(*) FROM eco_flags WHERE hard_safety=1 AND ts BETWEEN ? AND ?",
                 (frm, to), default=0)
dist_km = (db.scalar("SELECT COALESCE(SUM(distance_m),0) FROM trips WHERE start_ts BETWEEN ? AND ?",
                     (frm, to), default=0) or 0) / 1000
per100 = total / (dist_km / 100) if dist_km else 0
score = db.scalar("SELECT score FROM driver_score ORDER BY period_start DESC LIMIT 1")

# --- headline: four cards -------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
with c1:
    metric_card("Hard safety events", str(int(hard)),
                tone="alert" if hard else None,
                hint="extreme severity or severe speeding" if hard else "within normal range")
with c2:
    metric_card("Events per 100 km", f"{per100:.1f}",
                hint="no baseline yet — building from this period")
with c3:
    if total:
        vc = events["type"].value_counts()
        top_type, top_n = vc.index[0], int(vc.iloc[0])
        metric_card("Most common", TYPE_LABELS.get(top_type, top_type),
                    hint=f"{top_n} of {total} ({top_n * 100 // total}%)")
    else:
        metric_card("Most common", "—")
with c4:
    metric_card("Wialon score", f"{score:.1f}" if score is not None else "—", unit="/10",
                subtle=True, hint="reference · European calibration")

with st.expander("Why the Wialon score may not reflect local conditions"):
    st.markdown(
        "Wialon's 0–10 eco rank is calibrated for European fleets. On Kenyan roads, "
        "mild/medium harsh-brake, cornering and acceleration events fire constantly "
        "from potholes, unmarked bumps, mountain descents and unpredictable traffic — "
        "regardless of how the driver behaves — so the score reads structurally low "
        "(this unit: ~1/10) even with no extreme events. Treat it as a **reference** to "
        "cross-check Wialon's own UI, not as a verdict on the driver. The headline "
        "metrics above (hard-safety events, events per 100 km) are the actionable ones. "
        "See `docs/scoring.md`.")

# --- events worth attention (hard-safety only) ----------------------------
st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Events worth attention")
hs = db.q(
    "SELECT e.ts, e.type, f.severity, e.value, e.lat, e.lon, f.journey_character, e.raw "
    "FROM eco_events e JOIN eco_flags f ON f.unit_id=e.unit_id AND f.ts=e.ts AND f.type=e.type "
    "WHERE f.hard_safety=1 AND e.ts BETWEEN ? AND ? ORDER BY e.ts DESC", (frm, to))
if hs.empty:
    empty_state("No hard-safety events this period",
                "Driver behaviour is within normal range for the operating environment. "
                "Use the patterns below to track trends.")
else:
    import json as _json

    def _loc(raw):
        try:
            cell = _json.loads(raw)["c"][3]
            return cell.get("t") if isinstance(cell, dict) else cell
        except Exception:
            return "—"
    tbl = pd.DataFrame({
        "When": pd.to_datetime(hs["ts"], unit="s", utc=True),
        "Type": hs["type"].map(lambda t: TYPE_LABELS.get(t, t)),
        "Severity": hs["severity"],
        "Max km/h": hs["value"],
        "Where": hs["raw"].map(_loc),
        "Trip": hs["journey_character"],
        "Map": hs.apply(lambda r: f"https://maps.google.com/?q={r.lat},{r.lon}", axis=1),
    })
    st.dataframe(tbl, hide_index=True, use_container_width=True, column_config={
        "When": st.column_config.DatetimeColumn("When", format="DD MMM, HH:mm"),
        "Map": st.column_config.LinkColumn("Map", display_text="open")})

# --- night driving on highways (informational) ----------------------------
st.subheader("Night driving on highways")
nj = db.q(
    "SELECT start_ts, origin_place_id, dest_place_id, night_seconds FROM journeys "
    "WHERE is_local=0 AND journey_character IN ('long_haul','regional') "
    "AND night_seconds>0 AND start_ts BETWEEN ? AND ? ORDER BY start_ts DESC", (frm, to))
night_h = (nj["night_seconds"].sum() / 3600) if not nj.empty else 0
n1, n2 = st.columns(2)
with n1:
    metric_card("Night driving", f"{night_h:.1f}", "h", hint="19:00–05:00 local, on highways")
with n2:
    metric_card("Trips with night driving", str(len(nj)))
st.caption("Night driving increases fatigue and accident risk. Confirm with the operator "
           "whether night portions are scheduled or unplanned. **Inferred** from timestamps — "
           "engine-on at a fuel stop can look like night activity.")
if not nj.empty:
    def lbl(pid):
        return P.get(int(pid), "—") if not pd.isna(pid) else "—"
    nt = pd.DataFrame({
        "Date": pd.to_datetime(nj["start_ts"], unit="s", utc=True),
        "Route": nj["origin_place_id"].map(lbl) + " → " + nj["dest_place_id"].map(lbl),
        "Night driving (h)": (nj["night_seconds"] / 3600).round(1),
    })
    st.dataframe(nt, hide_index=True, use_container_width=True, column_config={
        "Date": st.column_config.DatetimeColumn("Date", format="DD MMM YYYY")})

# --- patterns over time ---------------------------------------------------
st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Patterns over time")
n_weeks = db.scalar("SELECT COUNT(*) FROM driver_score", default=0)
if n_weeks < 3:
    st.markdown("Patterns build with more data — need 3+ weeks for meaningful trend analysis.")
else:
    weeks = db.q("SELECT period_start, score, distance_m, accel_count, brake_count, "
                 "corner_count, speeding_count FROM driver_score ORDER BY period_start")
    weeks["week"] = pd.to_datetime(weeks["period_start"], unit="s", utc=True)
    events_total = weeks[["accel_count", "brake_count", "corner_count", "speeding_count"]].sum(axis=1)
    weeks["e100"] = events_total / (weeks["distance_m"] / 1000 / 100).replace(0, pd.NA)
    a, b = st.columns(2)
    with a:
        st.caption("Events per 100 km, weekly")
        f = px.line(weeks, x="week", y="e100", markers=True)
        f.update_traces(line_color=theme.ACCENT)
        st.plotly_chart(theme.style_fig(f, height=200), use_container_width=True)
    with b:
        st.caption("Event mix by type, weekly")
        mix = weeks.melt(id_vars="week",
                         value_vars=["accel_count", "brake_count", "corner_count", "speeding_count"],
                         var_name="type", value_name="n")
        f = px.bar(mix, x="week", y="n", color="type")
        st.plotly_chart(theme.style_fig(f, height=200), use_container_width=True)

# --- event breakdown (existing) -------------------------------------------
st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Event breakdown")
if not total:
    empty_state("No events in this period",
                "Eco Driving is configured on the device; events appear here as they occur.")
else:
    counts = events["type"].map(lambda t: TYPE_LABELS.get(t, t)).value_counts().reset_index()
    counts.columns = ["type", "count"]
    fig = px.bar(counts, x="count", y="type", orientation="h")
    fig.update_traces(marker_color=theme.ACCENT, hovertemplate="%{y}<br>%{x} events<extra></extra>")
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None)
    st.plotly_chart(theme.style_fig(fig, height=240), use_container_width=True)

# --- Wialon score over time (reference, bottom) ---------------------------
st.markdown('<hr/>', unsafe_allow_html=True)
st.subheader("Wialon score over time (reference)")
st.caption("Calibrated for European conditions and reads low on Kenyan routes — "
           "track the trend, not the absolute value.")
wk = db.q("SELECT period_start, score FROM driver_score ORDER BY period_start")
if len(wk) < 3:
    latest = wk.iloc[-1]["score"] if not wk.empty else None
    st.markdown(f"Score this week: **{latest:.1f}/10** — limited history; more weeks "
                "will appear as data accumulates." if latest is not None
                else "No score yet.")
else:
    wk["week"] = pd.to_datetime(wk["period_start"], unit="s", utc=True)
    fig = px.line(wk, x="week", y="score", markers=True)
    fig.update_traces(line_color=theme.MUTED, hovertemplate="week of %{x|%d %b}<br>%{y:.1f}/10<extra></extra>")
    fig.update_yaxes(range=[0, 10], dtick=2, title=None)
    fig.update_xaxes(title=None)
    st.plotly_chart(theme.style_fig(fig, height=220), use_container_width=True)
