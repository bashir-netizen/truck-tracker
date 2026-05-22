"""Per-trip derived metrics.

Rebuilds `trip_metrics`: fuel economy (L/100km), start/end place ids, and
the count of harsh events that fell within each trip's window.
"""

import config
from enrich import places as places_mod


def rebuild(con, unit_id):
    pls = places_mod.load_places(con)
    con.execute("DELETE FROM trip_metrics")

    rows = con.execute(
        "SELECT unit_id, start_ts, end_ts, start_lat, start_lon, end_lat, end_lon, "
        "       distance_m, consumed_l "
        "FROM trips WHERE unit_id=?", (unit_id,)).fetchall()

    out = []
    for uid, sts, ets, slat, slon, elat, elon, dist, consumed in rows:
        l_per_100km = None
        if consumed is not None and dist:
            km = dist / 1000.0
            if km >= config.MIN_ECONOMY_KM:  # skip noisy near-zero maneuvers
                l_per_100km = round(consumed / km * 100, 2)
        start_place = places_mod.nearest_place_id(pls, slat, slon)
        end_place = places_mod.nearest_place_id(pls, elat, elon)
        harsh = con.execute(
            "SELECT COUNT(*) FROM eco_events WHERE unit_id=? AND ts>=? AND ts<=? "
            "AND type IN ('harsh_accel','harsh_brake','harsh_corner')",
            (uid, sts, ets)).fetchone()[0]
        out.append((uid, sts, ets, start_place, end_place, l_per_100km, harsh, None))

    con.executemany(
        "INSERT INTO trip_metrics "
        "(unit_id, start_ts, end_ts, start_place_id, end_place_id, "
        " l_per_100km, harsh_event_count, idle_s) VALUES (?,?,?,?,?,?,?,?)", out)
    return len(out)
