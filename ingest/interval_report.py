"""Shared ingest for interval report tables (stops, parkings).

unit_stops and unit_stays return identical columns; only the Wialon table
type and the destination SQLite table differ. Idempotent: INSERT OR IGNORE
on (unit_id, start_ts).
"""

import json

from ingest import wialon

COLUMNS = "time_begin,time_end,duration,location,coord"


def parse_row(unit_id, row):
    c = row.get("c", [])
    if len(c) < 4:
        return None
    start_ts = wialon.cell_epoch(c[0]) or row.get("t1")
    if not start_ts:
        return None
    end_ts = wialon.cell_epoch(c[1]) or row.get("t2")
    lat, lon = wialon.cell_xy(c[0])
    duration_s = wialon.hms_to_seconds(c[2])
    if duration_s is None and end_ts:
        duration_s = int(end_ts) - int(start_ts)
    location = wialon.cell_text(c[3])
    return (unit_id, int(start_ts), int(end_ts) if end_ts else None, duration_s,
            lat, lon, location, json.dumps(row, ensure_ascii=False))


def fetch_and_store(client, con, unit_id, resource_id, ts_from, ts_to,
                    table_type, label, dest):
    """`dest` is an internal constant table name, never user input."""
    rows = client.run_table_report(resource_id, unit_id, ts_from, ts_to,
                                   table_type, label, COLUMNS)
    tuples = [t for t in (parse_row(unit_id, r) for r in rows) if t]
    before = con.total_changes
    con.executemany(
        f"INSERT OR IGNORE INTO {dest} "
        "(unit_id, start_ts, end_ts, duration_s, lat, lon, location, raw) "
        "VALUES (?,?,?,?,?,?,?,?)", tuples)
    return con.total_changes - before
