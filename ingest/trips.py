"""Fetch trips from the tuned (unit-level) trip detector and store them.

Idempotent: re-running over the same period inserts nothing new
(INSERT OR IGNORE on the natural key unit_id, start_ts, end_ts).
"""

import json

from ingest import wialon

TABLE_TYPE = "unit_trips"
LABEL = "Trips"
COLUMNS = "time_begin,time_end,duration,mileage,avg_speed,max_speed"


def parse_row(unit_id, row):
    """Map one raw report row to a trips table tuple, or None if unusable."""
    c = row.get("c", [])
    if len(c) < 6:
        return None
    start_ts = wialon.cell_epoch(c[0]) or row.get("t1")
    end_ts = wialon.cell_epoch(c[1]) or row.get("t2")
    if not start_ts or not end_ts:
        return None
    start_lat, start_lon = wialon.cell_xy(c[0])
    end_lat, end_lon = wialon.cell_xy(c[1])
    duration_s = wialon.hms_to_seconds(c[2])
    if duration_s is None:
        duration_s = int(end_ts) - int(start_ts)
    mileage_km = wialon.num(c[3])
    distance_m = int(round(mileage_km * 1000)) if mileage_km is not None else None
    avg_speed = wialon.num(c[4])
    max_speed = wialon.num(c[5])
    return (
        unit_id, int(start_ts), int(end_ts),
        start_lat, start_lon, end_lat, end_lon,
        distance_m, duration_s,
        int(round(avg_speed)) if avg_speed is not None else None,
        int(round(max_speed)) if max_speed is not None else None,
        json.dumps(row, ensure_ascii=False),
    )


UPSERT = (
    "INSERT INTO trips "
    "(unit_id, start_ts, end_ts, start_lat, start_lon, end_lat, end_lon, "
    " distance_m, duration_s, avg_speed_kmh, max_speed_kmh, raw) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(unit_id, start_ts) DO UPDATE SET "
    "  end_ts=excluded.end_ts, end_lat=excluded.end_lat, end_lon=excluded.end_lon, "
    "  distance_m=excluded.distance_m, duration_s=excluded.duration_s, "
    "  avg_speed_kmh=excluded.avg_speed_kmh, max_speed_kmh=excluded.max_speed_kmh, "
    "  raw=excluded.raw "
    "WHERE excluded.end_ts > trips.end_ts"  # only finalize a still-open trip
)


def fetch_and_store(client, con, unit_id, resource_id, ts_from, ts_to):
    """Pull trips for the window and upsert them. Returns genuinely-new rows.

    An in-progress trip seen again with a later end updates in place; only
    brand-new trips change the row count, so COUNT(*) delta is the true
    "added" figure.
    """
    rows = client.run_table_report(resource_id, unit_id, ts_from, ts_to,
                                   TABLE_TYPE, LABEL, COLUMNS)
    tuples = [t for t in (parse_row(unit_id, r) for r in rows) if t]
    before = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    con.executemany(UPSERT, tuples)
    after = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    return after - before
