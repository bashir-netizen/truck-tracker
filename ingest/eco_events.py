"""Fetch driver-behaviour (eco-driving) events and store them.

Wialon reports the violation kind as a human string in `violation_name`
(e.g. "Speeding: mild", "Harsh acceleration"). We map that to the five
canonical types; the original string (with its severity) is kept in `raw`.
The numeric magnitude is not exposed, so `value` holds max_speed (km/h)
as a proxy.

Idempotent: INSERT OR IGNORE on (unit_id, ts, type).
"""

import json

from ingest import wialon

TABLE_TYPE = "unit_ecodriving"
LABEL = "Eco driving"
COLUMNS = "time_begin,time_end,duration,location,violation_name,avg_speed,max_speed"


def classify(violation_name):
    """Map a Wialon violation string to a canonical event type."""
    s = (violation_name or "").lower()
    if "accel" in s:
        return "harsh_accel"
    if "brak" in s:
        return "harsh_brake"
    if "corner" in s or "turn" in s:
        return "harsh_corner"
    if "speed" in s:
        return "speeding"
    if "idl" in s:
        return "idling"
    return "other"


def parse_row(unit_id, row):
    c = row.get("c", [])
    if len(c) < 7:
        return None
    ts = wialon.cell_epoch(c[0]) or row.get("t1")
    if not ts:
        return None
    lat, lon = wialon.cell_xy(c[0])
    duration_s = wialon.hms_to_seconds(c[2])
    etype = classify(wialon.cell_text(c[4]))
    value = wialon.num(c[6])  # max_speed km/h, as a magnitude proxy
    return (
        unit_id, int(ts), etype, value, duration_s, lat, lon,
        json.dumps(row, ensure_ascii=False),
    )


def fetch_and_store(client, con, unit_id, resource_id, ts_from, ts_to):
    rows = client.run_table_report(resource_id, unit_id, ts_from, ts_to,
                                   TABLE_TYPE, LABEL, COLUMNS)
    tuples = [t for t in (parse_row(unit_id, r) for r in rows) if t]
    before = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO eco_events "
        "(unit_id, ts, type, value, duration_s, lat, lon, raw) "
        "VALUES (?,?,?,?,?,?,?,?)",
        tuples,
    )
    return con.total_changes - before
