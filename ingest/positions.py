"""Fetch and store the GPS track, decimated by distance.

Raw messages arrive every ~20s, including many redundant points while
parked. We keep a point only when it is at least TRACK_MIN_METERS from the
last kept point — sparse where stationary, dense enough to trace roads.

Idempotent: INSERT OR IGNORE on (unit_id, ts).
"""

import math

import config

EARTH_M = 6371000.0


def _haversine_m(lat1, lon1, lat2, lon2):
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(h))


def decimate(points, min_m):
    """Keep points (t, lat, lon, speed) at least min_m apart. Input ordered by t."""
    kept, last = [], None
    for t, lat, lon, spd in points:
        if t is None or lat is None or lon is None:
            continue
        if last is None or _haversine_m(last[0], last[1], lat, lon) >= min_m:
            kept.append((t, lat, lon, spd))
            last = (lat, lon)
    return kept


def fetch_and_store(client, con, unit_id, ts_from, ts_to):
    raw = client.load_positions(unit_id, ts_from, ts_to)
    raw.sort(key=lambda r: r[0] or 0)
    kept = decimate(raw, config.TRACK_MIN_METERS)
    tuples = [(unit_id, int(t), lat, lon, int(spd) if spd is not None else None)
              for (t, lat, lon, spd) in kept]
    before = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO positions (unit_id, ts, lat, lon, speed_kmh) "
        "VALUES (?,?,?,?,?)", tuples)
    return con.total_changes - before
