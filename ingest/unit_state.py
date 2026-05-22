"""Snapshot the unit's counters and last position once per run.

Reads from the already-fetched unit dict (from find_unit), so no extra
API call. Stores odometer in metres and engine hours in seconds per the
project conventions. Note: on this unit the `cnm` mileage counter looks
unreliable and `cneh` is 0 (engine-hours counter not configured in
Wialon) — enrichment derives a trustworthy odometer from trip mileage.

Idempotent: INSERT OR IGNORE on (unit_id, ts).
"""

import json
import time


def snapshot(con, unit):
    """Write one unit_state row from a find_unit result. Returns rows added."""
    pos = unit.get("pos") or {}
    ts = pos.get("t")
    if not ts:
        return 0
    cnm = unit.get("cnm")    # mileage counter, km
    cneh = unit.get("cneh")  # engine hours counter, h
    odometer_m = int(round(cnm * 1000)) if cnm is not None else None
    engine_hours_s = int(round(cneh * 3600)) if cneh is not None else None
    speed = pos.get("s")
    row = (
        unit["id"], int(ts), int(time.time()),
        pos.get("y"), pos.get("x"),
        int(speed) if speed is not None else None,
        odometer_m, engine_hours_s,
        json.dumps({"pos": pos, "cnm": cnm, "cneh": cneh}, ensure_ascii=False),
    )
    before = con.total_changes
    con.execute(
        "INSERT OR IGNORE INTO unit_state "
        "(unit_id, ts, captured_ts, lat, lon, speed_kmh, odometer_m, engine_hours_s, raw) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        row,
    )
    return con.total_changes - before
