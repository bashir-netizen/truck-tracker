"""Stitch trip legs into journeys — the real point-A-to-point-B runs.

Wialon splits one delivery run into many short "trips" at each fuel stop or
parking. A journey is a maximal run of consecutive legs separated only by gaps
shorter than JOURNEY_SPLIT_HOURS. Origin/destination place ids are filled in
later by assign_places(), once places have been clustered.
"""

import config
from enrich import places as places_mod


def character(distance_m, duration_s):
    """Bucket a journey by character from config.TRIP_THRESHOLDS."""
    th = config.TRIP_THRESHOLDS
    if (distance_m >= th["long_haul_min_distance_m"]
            or (duration_s or 0) >= th["long_haul_min_duration_s"]):
        return "long_haul"
    if distance_m >= th["regional_min_distance_m"]:
        return "regional"
    if distance_m >= th["local_min_distance_m"]:
        return "local"
    return "yard"


def night_overlap(start_ts, end_ts):
    """Seconds of [start,end] (UTC) inside the local 19:00-05:00 night window."""
    off = config.KENYA_UTC_OFFSET_H * 3600
    s, e = start_ts + off, end_ts + off
    total, day = 0, (s // 86400) * 86400
    while day <= e:
        ns = day + config.NIGHT_START_HOUR * 3600
        ne = day + (24 + config.NIGHT_END_HOUR) * 3600
        total += max(0, min(e, ne) - max(s, ns))
        day += 86400
    return total


def _split(legs, gap_s):
    run = []
    for leg in legs:
        if run and (leg["start_ts"] - run[-1]["end_ts"]) >= gap_s:
            yield run
            run = []
        run.append(leg)
    if run:
        yield run


def rebuild(con, unit_id):
    con.execute("DELETE FROM journeys")
    rows = con.execute(
        "SELECT start_ts, end_ts, start_lat, start_lon, end_lat, end_lon, "
        "       distance_m, duration_s, consumed_l "
        "FROM trips WHERE unit_id=? ORDER BY start_ts", (unit_id,)).fetchall()
    legs = [dict(start_ts=r[0], end_ts=r[1], slat=r[2], slon=r[3], elat=r[4],
                 elon=r[5], dist=r[6] or 0, dur=r[7] or 0, fuel=r[8] or 0.0)
            for r in rows]

    gap = config.JOURNEY_SPLIT_HOURS * 3600
    out = []
    for j in _split(legs, gap):
        dist = sum(x["dist"] for x in j)
        dur = sum(x["dur"] for x in j)
        fuel = sum(x["fuel"] for x in j)
        olat, olon = j[0]["slat"], j[0]["slon"]
        dlat, dlon = j[-1]["elat"], j[-1]["elon"]
        l100 = (round(fuel / (dist / 1000.0) * 100, 2)
                if dist >= config.MIN_ECONOMY_KM * 1000 and fuel else None)
        is_local = 1 if dist < config.ROUTE_MIN_KM * 1000 else 0
        if not is_local and None not in (olat, olon, dlat, dlon):
            if places_mod.haversine_m(olat, olon, dlat, dlon) < config.PLACE_EPS_M:
                is_local = 1  # returned to its own origin area
        night = sum(night_overlap(x["start_ts"], x["end_ts"]) for x in j)
        out.append((unit_id, j[0]["start_ts"], j[-1]["end_ts"], olat, olon, dlat, dlon,
                    len(j), dist, dur, fuel, l100, is_local, character(dist, dur), night))

    con.executemany(
        "INSERT INTO journeys (unit_id, start_ts, end_ts, origin_lat, origin_lon, "
        "dest_lat, dest_lon, leg_count, distance_m, duration_s, fuel_l, l_per_100km, "
        "is_local, journey_character, night_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    return len(out)


def assign_places(con, unit_id):
    """Back-fill origin/dest place ids on journeys (places must exist first)."""
    pls = places_mod.load_places(con)
    for jid, olat, olon, dlat, dlon in con.execute(
            "SELECT journey_id, origin_lat, origin_lon, dest_lat, dest_lon "
            "FROM journeys WHERE unit_id=?", (unit_id,)).fetchall():
        con.execute(
            "UPDATE journeys SET origin_place_id=?, dest_place_id=? WHERE journey_id=?",
            (places_mod.nearest_place_id(pls, olat, olon),
             places_mod.nearest_place_id(pls, dlat, dlon), jid))
