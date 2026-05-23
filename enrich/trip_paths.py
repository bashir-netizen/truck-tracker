"""Per-trip GPS paths (RDP-simplified) for the Map's multi-trip view + playback.

Derived from raw `positions` between each trip's start/end, reusing the corridor
RDP simplifier. Runs over ALL trips. A trip with no GPS in its window is recorded
with a NULL path (point_count=0) and logged — never dropped, never fatal — so the
Map can fall back to a dashed straight line (start->end from `trips`).

Class comes from the journey that contains the trip, so journeys.rebuild() must
run first. Display colour (date->palette) is decided at render time, not here.
"""

import json

from enrich.corridors import _rdp

RDP_EPS_M = 50.0


def _class_for(journeys, ts):
    """journey_character of the journey whose window contains ts, else None."""
    for s, e, ch in journeys:
        if s <= ts <= (e if e is not None else s):
            return ch
    return None


def rebuild(con, unit_id):
    con.execute("DELETE FROM trip_paths")
    jrows = con.execute(
        "SELECT start_ts, end_ts, journey_character FROM journeys "
        "WHERE unit_id=? ORDER BY start_ts", (unit_id,)).fetchall()
    trips = con.execute(
        "SELECT start_ts, end_ts FROM trips WHERE unit_id=? ORDER BY start_ts",
        (unit_id,)).fetchall()

    out, no_gps = [], 0
    for sts, ets in trips:
        pts = [(lo, la) for lo, la in con.execute(
            "SELECT lon, lat FROM positions WHERE unit_id=? AND ts BETWEEN ? AND ? ORDER BY ts",
            (unit_id, sts, ets)).fetchall() if lo is not None and la is not None]
        path = _rdp(pts, RDP_EPS_M) if len(pts) >= 2 else None
        cls = _class_for(jrows, sts)
        if path:
            out.append((unit_id, sts, ets, cls, len(path), json.dumps(path)))
        else:
            no_gps += 1
            out.append((unit_id, sts, ets, cls, 0, None))

    con.executemany(
        "INSERT INTO trip_paths (unit_id, start_ts, end_ts, journey_class, "
        "point_count, path_geojson) VALUES (?,?,?,?,?,?)", out)
    if no_gps:
        print(f"  trip_paths: {no_gps} trip(s) had no GPS in window — "
              "stored NULL path (Map uses straight-line fallback)")
    return len(out)
