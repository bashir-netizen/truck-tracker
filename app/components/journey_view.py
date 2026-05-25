"""Journey View — one round trip on the Map.

Shows a single round trip end to end: outbound + return as one visual unit
(outbound solid accent, return translucent — pydeck PathLayer can't dash), with
sequential numbered waypoints, a chronological timeline, and the events that
happened on the trip. Everything is reconstructed READ-ONLY from existing tables
(round_trips / journeys / trips / trip_paths / place_visits / places / fillings /
eco_flags / stops); this module writes nothing and does not call Wialon.

Opened from the Overview via ?round_trip=<id>; pages/1_Map.py renders Mode 1
(period overview) when no round trip is selected and calls render() otherwise.
"""

import json
from collections import Counter

import pandas as pd
import pydeck as pdk
import streamlit as st

import config
from app.components import db, theme
from app.components.empty_state import empty_state
from app.components.map_helpers import (ARROW_KM, EVENT_NAME, EVENT_RGB, TYPE_LABELS,
                                        fit_view, sample_arrows)

CLASS_LABELS = getattr(theme, "CLASS_LABELS", {
    "long_haul": "long haul", "regional": "regional", "local": "local", "yard": "yard"})

OUTBOUND_RGB = [196, 61, 47]          # accent red, full opacity (outbound leg)
RETURN_RGB = [196, 61, 47, 105]       # same red, translucent (return leg)
FALLBACK_RGB = [138, 146, 163, 150]   # gray — a leg with no GPS (matches the period Map)
DEPOT_RGB = [63, 125, 88]             # green — home base
PRIMARY_RGB = [196, 61, 47]           # accent — the primary destination
WAYPOINT_RGB = [120, 116, 108]        # neutral — an intermediate stop
LONG_STOP_S = 7200                    # 2 h — a "long stop" event (matches the period Map)


# ---- reconstruction (read-only) ------------------------------------------

def load(rt_id):
    """The round-trip header row as a dict, or None."""
    df = db.q("SELECT round_trip_id, unit_id, start_ts, end_ts, primary_destination_id, "
              "primary_destination_name, journey_class, total_distance_km, total_duration_s, "
              "via_places, return_via_places FROM round_trips WHERE round_trip_id=?", (rt_id,))
    if df.empty:
        return None
    r = df.iloc[0]
    return {
        "id": int(r.round_trip_id), "unit_id": int(r.unit_id),
        "start_ts": int(r.start_ts), "end_ts": int(r.end_ts),
        "primary_id": None if pd.isna(r.primary_destination_id) else int(r.primary_destination_id),
        "primary_name": r.primary_destination_name, "cls": r.journey_class,
        "km": float(r.total_distance_km or 0), "dur_s": int(r.total_duration_s or 0),
        "via": json.loads(r.via_places or "[]"), "rvia": json.loads(r.return_via_places or "[]")}


def load_cycle(cycle_id):
    """A delivery cycle (Task 10) normalized into the same shape as a round trip, or None."""
    df = db.q("SELECT cycle_id, unit_id, cycle_start_ts, cycle_end_ts, destination_place_id, "
              "destination_place_name, cycle_type, total_distance_km, total_duration_s, "
              "via_places, constituent_journey_ids FROM delivery_cycles WHERE cycle_id=?", (cycle_id,))
    if df.empty:
        return None
    r = df.iloc[0]
    end = None if pd.isna(r.cycle_end_ts) else int(r.cycle_end_ts)
    if end is None:                                  # incomplete: use the last constituent journey
        jids = json.loads(r.constituent_journey_ids or "[]")
        if jids:
            ph = ",".join("?" * len(jids))
            end = db.scalar(f"SELECT MAX(end_ts) FROM journeys WHERE journey_id IN ({ph})",
                            tuple(jids))
    return {
        "id": int(r.cycle_id), "unit_id": int(r.unit_id), "start_ts": int(r.cycle_start_ts),
        "end_ts": int(end) if end else int(r.cycle_start_ts),
        "primary_id": None if pd.isna(r.destination_place_id) else int(r.destination_place_id),
        "primary_name": r.destination_place_name, "cls": r.cycle_type,
        "km": float(r.total_distance_km or 0), "dur_s": int(r.total_duration_s or 0),
        "via": json.loads(r.via_places or "[]"), "rvia": []}


def _journeys(rt):
    """Constituent journeys in order (the round trip is contiguous depot->depot)."""
    return db.q("SELECT journey_id, start_ts, end_ts, origin_place_id, dest_place_id "
                "FROM journeys WHERE unit_id=? AND start_ts>=? AND end_ts<=? ORDER BY start_ts",
                (rt["unit_id"], rt["start_ts"], rt["end_ts"]))


def _turnaround_ts(rt, jdf):
    """When the truck reached the primary destination — splits outbound from return."""
    if rt["primary_id"] is None or jdf.empty:
        return rt["end_ts"]
    hit = jdf[jdf["dest_place_id"] == rt["primary_id"]]
    return int(hit.iloc[0]["end_ts"]) if not hit.empty else rt["end_ts"]


def path_segments(rt, turn):
    """One segment per constituent trip: {path, fallback, is_return}."""
    tdf = db.q(
        "SELECT t.start_ts, t.start_lat, t.start_lon, t.end_lat, t.end_lon, tp.path_geojson "
        "FROM trips t LEFT JOIN trip_paths tp ON tp.unit_id=t.unit_id AND tp.start_ts=t.start_ts "
        "WHERE t.unit_id=? AND t.start_ts>=? AND t.end_ts<=? ORDER BY t.start_ts",
        (rt["unit_id"], rt["start_ts"], rt["end_ts"]))
    segs = []
    for r in tdf.itertuples():
        coords = json.loads(r.path_geojson) if isinstance(r.path_geojson, str) else None
        fb = coords is None
        if fb:
            if pd.isna(r.start_lat) or pd.isna(r.end_lat):
                continue
            coords = [[r.start_lon, r.start_lat], [r.end_lon, r.end_lat]]
        segs.append({"path": coords, "fallback": fb, "is_return": int(r.start_ts) >= turn})
    return segs


def waypoints(rt, jdf, depot_ids):
    """Ordered stops (depot -> … -> depot): seq, name, lat, lon, type, arrival/departure, dwell."""
    if jdf.empty:
        return []
    rows = list(jdf.itertuples())
    raw = [{"pid": rows[0].origin_place_id, "arrival": None, "departure": int(rows[0].start_ts)}]
    for k, j in enumerate(rows):
        nxt = int(rows[k + 1].start_ts) if k + 1 < len(rows) else None
        raw.append({"pid": j.dest_place_id, "arrival": int(j.end_ts), "departure": nxt})

    out = []
    for s in raw:
        pid = s["pid"]
        if pid is None or pd.isna(pid):
            continue
        pid = int(pid)
        p = db.q("SELECT label, lat, lon, type FROM places WHERE place_id=?", (pid,))
        if p.empty:
            continue
        pr = p.iloc[0]
        dwell = 0
        if s["arrival"] and s["departure"]:
            pv = db.scalar("SELECT duration_s FROM place_visits WHERE place_id=? AND ts<=? "
                           "ORDER BY ts DESC LIMIT 1", (pid, s["arrival"]), 0)
            dwell = int(pv) if pv else (s["departure"] - s["arrival"])
        out.append({"place_id": pid, "name": pr.label, "lat": float(pr.lat), "lon": float(pr.lon),
                    "type": pr.type or "destination", "arrival_ts": s["arrival"],
                    "departure_ts": s["departure"], "dwell_s": dwell,
                    "is_depot": pid in depot_ids, "is_primary": pid == rt["primary_id"]})
    for i, w in enumerate(out, 1):
        w["seq"] = i
    return out


def events(rt):
    """Fuel fills, eco violations, and long (>=2h) stops within the trip window, time-ordered."""
    s, e, u = rt["start_ts"], rt["end_ts"], rt["unit_id"]
    out = []
    for r in db.q("SELECT ts, lat, lon, volume_l FROM fillings WHERE unit_id=? AND ts BETWEEN ? AND ?",
                  (u, s, e)).itertuples():
        if not pd.isna(r.lat):
            out.append({"kind": "fill", "ts": int(r.ts), "lat": float(r.lat), "lon": float(r.lon),
                        "detail": f"{(r.volume_l or 0):.0f} L filled", "radius": 9})
    for r in db.q("SELECT e.ts, e.lat, e.lon, e.type, f.severity FROM eco_events e "
                  "JOIN eco_flags f ON f.unit_id=e.unit_id AND f.ts=e.ts AND f.type=e.type "
                  "WHERE e.unit_id=? AND e.ts BETWEEN ? AND ?", (u, s, e)).itertuples():
        if not pd.isna(r.lat):
            out.append({"kind": "harsh", "ts": int(r.ts), "lat": float(r.lat), "lon": float(r.lon),
                        "etype": r.type, "severity": r.severity, "radius": 7,
                        "detail": f"{TYPE_LABELS.get(r.type, r.type)} ({r.severity or 'n/a'})"})
    for r in db.q("SELECT start_ts, duration_s, lat, lon FROM stops "
                  "WHERE unit_id=? AND start_ts BETWEEN ? AND ? AND duration_s>=?",
                  (u, s, e, LONG_STOP_S)).itertuples():
        if not pd.isna(r.lat):
            out.append({"kind": "stop", "ts": int(r.start_ts), "lat": float(r.lat),
                        "lon": float(r.lon), "radius": 9,
                        "detail": f"Stopped {theme.fmt_dur(r.duration_s)}"})
    out.sort(key=lambda x: x["ts"])
    return out


# ---- rendering -----------------------------------------------------------

def _back():
    """Return to the Overview cleanly (drop the round-trip selection)."""
    st.query_params.clear()
    st.session_state.pop("journey_rt", None)
    st.session_state.pop("jv_sel", None)
    st.session_state.pop("jv_focus", None)
    st.switch_page("main.py")


def render(kind, ident):
    rt = load(ident) if kind == "round_trip" else load_cycle(ident)
    noun = "run" if kind == "round_trip" else "delivery"
    if st.button("← Back to Overview", key="jv_back"):
        _back()
    if rt is None:
        empty_state("Journey not found", "This round trip is no longer in the data.")
        return

    jdf = _journeys(rt)
    turn = _turnaround_ts(rt, jdf)
    depot_ids = {int(x) for x in db.q("SELECT place_id FROM places WHERE type='depot'")
                 ["place_id"].tolist()}
    segs = path_segments(rt, turn)
    wps = waypoints(rt, jdf, depot_ids)
    evs = events(rt)

    # --- header ---------------------------------------------------------
    prim = rt["primary_name"] or ("Round trip" if kind == "round_trip" else "Delivery")
    start_name = wps[0]["name"] if wps else "—"
    end_name = wps[-1]["name"] if wps else "—"
    if kind == "round_trip":
        via_bits = []
        if rt["via"]:
            via_bits.append("via " + ", ".join(rt["via"]) + " (outbound)")
        if rt["rvia"]:
            via_bits.append(", ".join(rt["rvia"]) + " (return)")
    else:
        via_bits = ["via " + ", ".join(rt["via"])] if rt["via"] else []
    st.markdown(
        f'<div class="tt-card"><div style="display:flex;justify-content:space-between;'
        f'align-items:baseline;gap:.5rem"><div class="tt-h2" style="margin:0">{prim} {noun} '
        f'<span class="tt-pill neutral">{CLASS_LABELS.get(rt["cls"], rt["cls"])}</span></div>'
        f'{theme.confidence_badge("inferred")}</div>'
        f'<div class="tt-small">{theme.fmt_dt(rt["start_ts"])} → {theme.fmt_dt(rt["end_ts"])} · '
        f'~{rt["km"]:,.0f} km · {theme.fmt_dur(rt["dur_s"])}</div>'
        f'<div class="tt-small"><b>{start_name} → {prim} → {end_name}</b></div>'
        + (f'<div class="tt-small">{" · ".join(via_bits)}</div>' if via_bits else '')
        + '</div>', unsafe_allow_html=True)

    # --- map ------------------------------------------------------------
    layers = []
    out_solid = [s for s in segs if not s["fallback"] and not s["is_return"]]
    ret_solid = [s for s in segs if not s["fallback"] and s["is_return"]]
    fb = [s for s in segs if s["fallback"]]
    for lid, data, color in (("jv_out", out_solid, OUTBOUND_RGB), ("jv_ret", ret_solid, RETURN_RGB)):
        if data:
            layers.append(pdk.Layer("PathLayer", id=lid, data=data, get_path="path",
                                    get_color=color, get_width=6, width_units="pixels",
                                    width_min_pixels=3, cap_rounded=True, joint_rounded=True))
    if fb:
        layers.append(pdk.Layer("PathLayer", id="jv_fb", data=fb, get_path="path",
                                get_color=FALLBACK_RGB, get_width=2, width_units="pixels",
                                width_min_pixels=1))
    arrows = []
    for s in segs:
        if not s["fallback"]:
            arrows += sample_arrows(s["path"], ARROW_KM.get(rt["cls"], 3.0), min_arrows=1)
    if arrows:
        layers.append(pdk.Layer("IconLayer", id="jv_arrows", data=arrows, get_icon="icon",
                                get_position="position", get_angle="angle", get_size=15,
                                size_units="pixels", pickable=False))
    for kind in ("fill", "harsh", "stop"):
        sub = [e for e in evs if e["kind"] == kind]
        if sub:
            ed = pd.DataFrame(sub)
            ed["fill"] = [EVENT_RGB[kind] + [235]] * len(ed)
            ed["name"] = EVENT_NAME[kind] + " · " + ed["detail"]
            layers.append(pdk.Layer(
                "ScatterplotLayer", id=f"jev_{kind}", data=ed, get_position=["lon", "lat"],
                get_radius="radius", radius_units="pixels", radius_min_pixels=4,
                get_fill_color="fill", pickable=True, stroked=True,
                get_line_color=[255, 255, 255, 230], line_width_min_pixels=1))
    if wps:
        wdf = pd.DataFrame([{
            "seq": str(w["seq"]), "lat": w["lat"], "lon": w["lon"], "place_id": w["place_id"],
            "fill": (DEPOT_RGB + [240]) if w["is_depot"] else
                    ((PRIMARY_RGB + [240]) if w["is_primary"] else (WAYPOINT_RGB + [240])),
            "radius": 17 if w["is_primary"] else 13,
            "name": f'{w["seq"]}. {w["name"]} · {w["type"]}'
                    + (f' · {theme.fmt_dur(w["dwell_s"])}' if w["dwell_s"] else '')}
            for w in wps])
        layers.append(pdk.Layer(
            "ScatterplotLayer", id="jv_wp", data=wdf, get_position=["lon", "lat"],
            get_radius="radius", radius_units="pixels", radius_min_pixels=8, get_fill_color="fill",
            pickable=True, stroked=True, get_line_color=[255, 255, 255, 235], line_width_min_pixels=2))
        layers.append(pdk.Layer(
            "TextLayer", id="jv_wpnum", data=wdf, get_position=["lon", "lat"], get_text="seq",
            get_size=13, get_color=[255, 255, 255], pickable=False))

    all_lats = [pt[1] for s in segs for pt in s["path"]] + [w["lat"] for w in wps]
    all_lons = [pt[0] for s in segs for pt in s["path"]] + [w["lon"] for w in wps]
    focus = st.session_state.get("jv_focus")
    view = (pdk.ViewState(latitude=focus[0], longitude=focus[1], zoom=12)
            if focus else fit_view(all_lats, all_lons))
    sel = st.pydeck_chart(
        pdk.Deck(layers=layers, initial_view_state=view, map_style=theme.MAP_STYLE,
                 tooltip={"html": "<b>{name}</b>",
                          "style": {"backgroundColor": theme.INK, "color": "white",
                                    "fontSize": "12px", "borderRadius": "8px"}}),
        on_select="rerun", selection_mode="single-object", key="journeysel", width="stretch")

    leg = (f'<span style="color:{theme.MUTED}">'
           f'<span style="color:rgb(196,61,47)">━</span> outbound &nbsp; '
           f'<span style="color:rgba(196,61,47,.45)">━</span> return &nbsp; → direction</span> &nbsp; '
           f'<span class="dot" style="background:rgb{tuple(DEPOT_RGB)}"></span>depot &nbsp;'
           f'<span class="dot" style="background:rgb{tuple(PRIMARY_RGB)}"></span>destination &nbsp;'
           f'<span class="dot" style="background:rgb{tuple(WAYPOINT_RGB)}"></span>waypoint')
    st.markdown(f'<div class="tt-legend tt-micro" style="font-weight:500">{leg}</div>',
                unsafe_allow_html=True)

    # --- selection drill-in (waypoint / event) -------------------------
    _process_selection(sel, wps, evs)

    # --- timeline -------------------------------------------------------
    st.markdown('<div class="tt-h3" style="margin-top:1rem">Timeline</div>', unsafe_allow_html=True)
    st.markdown(_timeline_html(wps), unsafe_allow_html=True)

    # --- events ---------------------------------------------------------
    st.markdown('<div class="tt-h3" style="margin-top:1rem">Events on this journey</div>',
                unsafe_allow_html=True)
    _events_section(evs)


def _process_selection(sel, wps, evs):
    objects = {}
    try:
        objects = sel["selection"]["objects"] or {}
    except Exception:
        objects = {}
    if objects.get("jv_wp"):
        st.session_state["jv_sel"] = {"kind": "wp", "place_id": int(objects["jv_wp"][0]["place_id"])}
        st.session_state.pop("jv_focus", None)
    else:
        for k in ("jev_harsh", "jev_fill", "jev_stop"):
            if objects.get(k):
                o = objects[k][0]
                st.session_state["jv_sel"] = {"kind": "ev", "name": o.get("name", "event")}
                break

    s = st.session_state.get("jv_sel")
    if not s:
        return
    a, b = st.columns([5, 1])
    if s["kind"] == "wp":
        w = next((x for x in wps if x["place_id"] == s["place_id"]), None)
        if w:
            n_ev = sum(1 for e in evs if w["arrival_ts"] and w["departure_ts"]
                       and w["arrival_ts"] <= e["ts"] <= w["departure_ts"])
            arr = theme.fmt_dt(w["arrival_ts"]) if w["arrival_ts"] else "—"
            stay = theme.fmt_dur(w["dwell_s"]) if w["dwell_s"] else "pass-through"
            a.markdown(
                f'<div class="tt-card"><div class="lbl">stop {w["seq"]}</div>'
                f'<div style="margin:.2rem 0"><b>{w["name"]}</b> '
                f'<span class="tt-pill neutral">{w["type"]}</span></div>'
                f'<div class="tt-small">Arrived {arr} · stayed {stay}</div>'
                + (f'<div class="tt-small">{n_ev} event(s) at this stop</div>' if n_ev else '')
                + '</div>', unsafe_allow_html=True)
    else:
        a.markdown(f'<div class="tt-card"><div class="lbl">event</div>'
                   f'<div style="margin:.2rem 0"><b>{s["name"]}</b></div></div>',
                   unsafe_allow_html=True)
    if b.button("Clear", key="jv_clearsel"):
        st.session_state.pop("jv_sel", None)
        st.rerun()


def _timeline_html(wps):
    if not wps:
        return '<div class="tt-small">No waypoints reconstructed for this trip.</div>'
    rows = []
    last = len(wps)
    for w in wps:
        when = theme.fmt_dt(w["departure_ts"] if w["arrival_ts"] is None else w["arrival_ts"])
        if w["arrival_ts"] is None:
            action = f"Departed {w['name']}"
        elif w["seq"] == last and w["is_depot"]:
            action = f"Returned to {w['name']}"
        else:
            action = f"Arrived {w['name']}"
            if w["dwell_s"] and w["dwell_s"] >= config.PLACE_MIN_DWELL_S:
                action += f' · stayed {theme.fmt_dur(w["dwell_s"])}'
        rows.append(f'<div class="tt-small" style="padding:.15rem 0">'
                    f'<b>{w["seq"]}.</b> {when} — {action}</div>')
    return '<div>' + "".join(rows) + '</div>'


def _events_section(evs):
    if not evs:
        st.caption("No fuel fills, violations, or long stops recorded on this trip.")
        return
    fills = [e for e in evs if e["kind"] == "fill"]
    harsh = [e for e in evs if e["kind"] == "harsh"]
    stops = [e for e in evs if e["kind"] == "stop"]
    parts = []
    if harsh:
        by = Counter(TYPE_LABELS.get(e["etype"], e["etype"]).lower() for e in harsh)
        parts.append(f"{len(harsh)} violation{'s' if len(harsh) != 1 else ''} ("
                     + ", ".join(f"{n} {name}" for name, n in by.most_common()) + ")")
    if fills:
        parts.append(f"{len(fills)} fuel fill{'s' if len(fills) != 1 else ''}")
    if stops:
        parts.append(f"{len(stops)} long stop{'s' if len(stops) != 1 else ''}")
    st.markdown(f'<div class="tt-small" style="margin-bottom:.3rem">{" · ".join(parts)}</div>',
                unsafe_allow_html=True)
    for e in evs:
        c1, c2 = st.columns([5, 1])
        c1.markdown(f'<div class="tt-small">{theme.fmt_dt(e["ts"])} · {EVENT_NAME[e["kind"]]} · '
                    f'{e["detail"]}</div>', unsafe_allow_html=True)
        if c2.button("Show", key=f"jvev_{e['kind']}_{e['ts']}"):
            st.session_state["jv_focus"] = (e["lat"], e["lon"])
            st.session_state.pop("jv_sel", None)
            st.rerun()
