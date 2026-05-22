"""Aggregate journeys into corridors — routes by unordered place pair.

Nairobi→Marsabit and Marsabit→Nairobi are the same corridor. Only non-local
journeys whose endpoints resolve to two different places are counted. Each
corridor caches the actual GPS path of its most recent journey (RDP-simplified)
so the map draws the real road, not a straight centroid line.
"""

import json
import math
from collections import defaultdict


def _rdp(points, eps_m):
    """Ramer–Douglas–Peucker on [(lon,lat),…], tolerance in metres. Iterative."""
    n = len(points)
    if n < 3:
        return list(points)
    lat0 = math.radians(sum(p[1] for p in points) / n)
    kx, ky = math.cos(lat0) * 111320.0, 110540.0

    def perp(p, a, b):
        px, py = p[0] * kx, p[1] * ky
        ax, ay = a[0] * kx, a[1] * ky
        bx, by = b[0] * kx, b[1] * ky
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        dmax, idx = 0.0, -1
        for i in range(a + 1, b):
            d = perp(points[i], points[a], points[b])
            if d > dmax:
                dmax, idx = d, i
        if idx != -1 and dmax > eps_m:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [points[i] for i in range(n) if keep[i]]


def _journey_path(con, unit_id, start_ts, end_ts):
    rows = con.execute(
        "SELECT lon, lat FROM positions WHERE unit_id=? AND ts BETWEEN ? AND ? ORDER BY ts",
        (unit_id, start_ts, end_ts)).fetchall()
    pts = [(lo, la) for lo, la in rows if lo is not None and la is not None]
    return _rdp(pts, 50.0) if len(pts) >= 2 else None


def rebuild(con, unit_id):
    con.execute("DELETE FROM corridors")
    rows = con.execute(
        "SELECT origin_place_id, dest_place_id, distance_m, duration_s, fuel_l, start_ts, end_ts "
        "FROM journeys WHERE unit_id=? AND is_local=0 "
        "AND origin_place_id IS NOT NULL AND dest_place_id IS NOT NULL "
        "AND origin_place_id <> dest_place_id", (unit_id,)).fetchall()

    agg = defaultdict(lambda: dict(n=0, dist=0, dur=0, fuel=0.0, first=None, last=None,
                                   latest_ts=None, latest_win=None))
    for o, d, dist, dur, fuel, ts, end_ts in rows:
        key = (o, d) if o < d else (d, o)
        g = agg[key]
        g["n"] += 1
        g["dist"] += dist or 0
        g["dur"] += dur or 0
        g["fuel"] += fuel or 0.0
        g["first"] = ts if g["first"] is None else min(g["first"], ts)
        g["last"] = ts if g["last"] is None else max(g["last"], ts)
        if g["latest_ts"] is None or ts > g["latest_ts"]:
            g["latest_ts"], g["latest_win"] = ts, (ts, end_ts)

    out = []
    for (a, b), g in agg.items():
        avg = round(g["fuel"] / (g["dist"] / 1000.0) * 100, 2) if g["dist"] else None
        path = _journey_path(con, unit_id, *g["latest_win"]) if g["latest_win"] else None
        out.append((a, b, g["n"], g["dist"], g["dur"], g["fuel"], avg, g["first"], g["last"],
                    json.dumps(path) if path else None))

    con.executemany(
        "INSERT INTO corridors (place_a_id, place_b_id, journey_count, total_distance_m, "
        "total_duration_s, total_fuel_l, avg_l_per_100km, first_seen_ts, last_seen_ts, "
        "path_geojson) VALUES (?,?,?,?,?,?,?,?,?,?)", out)
    return len(out)
