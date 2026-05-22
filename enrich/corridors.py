"""Aggregate journeys into corridors — routes by unordered place pair.

Nairobi→Marsabit and Marsabit→Nairobi are the same corridor. Only non-local
journeys whose endpoints resolve to two different places are counted.
"""

from collections import defaultdict


def rebuild(con, unit_id):
    con.execute("DELETE FROM corridors")
    rows = con.execute(
        "SELECT origin_place_id, dest_place_id, distance_m, duration_s, fuel_l, start_ts "
        "FROM journeys WHERE unit_id=? AND is_local=0 "
        "AND origin_place_id IS NOT NULL AND dest_place_id IS NOT NULL "
        "AND origin_place_id <> dest_place_id", (unit_id,)).fetchall()

    agg = defaultdict(lambda: dict(n=0, dist=0, dur=0, fuel=0.0, first=None, last=None))
    for o, d, dist, dur, fuel, ts in rows:
        key = (o, d) if o < d else (d, o)
        g = agg[key]
        g["n"] += 1
        g["dist"] += dist or 0
        g["dur"] += dur or 0
        g["fuel"] += fuel or 0.0
        g["first"] = ts if g["first"] is None else min(g["first"], ts)
        g["last"] = ts if g["last"] is None else max(g["last"], ts)

    out = []
    for (a, b), g in agg.items():
        avg = round(g["fuel"] / (g["dist"] / 1000.0) * 100, 2) if g["dist"] else None
        out.append((a, b, g["n"], g["dist"], g["dur"], g["fuel"], avg, g["first"], g["last"]))

    con.executemany(
        "INSERT INTO corridors (place_a_id, place_b_id, journey_count, total_distance_m, "
        "total_duration_s, total_fuel_l, avg_l_per_100km, first_seen_ts, last_seen_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?)", out)
    return len(out)
