"""Fetch fuel fillings and store them.

The fill's canonical time is the END of the fill event (when the level
settles). After-level is not exposed as a column, so we derive it as
before + filled (verified to match Wialon's own "Final fuel level").

Idempotent: INSERT OR IGNORE on (unit_id, ts).
"""

import json

from ingest import wialon

TABLE_TYPE = "unit_fillings"
LABEL = "Fuel fillings"
COLUMNS = "time_begin,time_end,filled,fuel_level_begin,sensor_name"


def parse_row(unit_id, row):
    c = row.get("c", [])
    if len(c) < 4:
        return None
    ts = wialon.cell_epoch(c[1]) or row.get("t2")  # time_end = fill completed
    if not ts:
        return None
    lat, lon = wialon.cell_xy(c[1])
    volume_l = wialon.num(c[2])
    level_before_l = wialon.num(c[3])
    level_after_l = None
    if level_before_l is not None and volume_l is not None:
        level_after_l = round(level_before_l + volume_l, 2)
    return (
        unit_id, int(ts), lat, lon,
        volume_l, level_before_l, level_after_l,
        json.dumps(row, ensure_ascii=False),
    )


def fetch_and_store(client, con, unit_id, resource_id, ts_from, ts_to):
    rows = client.run_table_report(resource_id, unit_id, ts_from, ts_to,
                                   TABLE_TYPE, LABEL, COLUMNS)
    tuples = [t for t in (parse_row(unit_id, r) for r in rows) if t]
    before = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO fillings "
        "(unit_id, ts, lat, lon, volume_l, level_before_l, level_after_l, raw) "
        "VALUES (?,?,?,?,?,?,?,?)",
        tuples,
    )
    return con.total_changes - before
