"""Rolling driver score per ISO week.

Rebuilds `driver_score`. For each week, eco events are weighted
(config.ECO_WEIGHTS), normalised per 100 km driven that week, and turned
into a 0..100 score (higher = better). Distance comes from trips.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import config


def week_start(ts):
    """Epoch of the Monday 00:00 UTC for the week containing ts."""
    dt = datetime.fromtimestamp(ts, timezone.utc)
    monday = (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return int(monday.timestamp())


def rebuild(con, unit_id):
    con.execute("DELETE FROM driver_score")

    counts = defaultdict(lambda: defaultdict(int))  # week -> type -> n
    distance_km = defaultdict(float)                 # week -> km
    weeks = set()

    for ts, etype in con.execute(
            "SELECT ts, type FROM eco_events WHERE unit_id=?", (unit_id,)):
        w = week_start(ts)
        counts[w][etype] += 1
        weeks.add(w)

    for sts, dist in con.execute(
            "SELECT start_ts, distance_m FROM trips WHERE unit_id=?", (unit_id,)):
        w = week_start(sts)
        distance_km[w] += (dist or 0) / 1000.0
        weeks.add(w)

    out = []
    for w in sorted(weeks):
        c = counts[w]
        penalty = sum(config.ECO_WEIGHTS.get(t, 1.0) * n for t, n in c.items())
        km = distance_km[w]
        rate = penalty / (km / 100.0) if km > 0 else penalty
        score = max(0.0, min(100.0, 100.0 - rate * config.SCORE_PENALTY_SCALE))
        out.append((
            unit_id, w, w + 7 * 86400, round(score, 1), int(round(km * 1000)),
            c.get("harsh_accel", 0), c.get("harsh_brake", 0),
            c.get("harsh_corner", 0), c.get("speeding", 0),
        ))

    con.executemany(
        "INSERT INTO driver_score "
        "(unit_id, period_start, period_end, score, distance_m, "
        " accel_count, brake_count, corner_count, speeding_count) "
        "VALUES (?,?,?,?,?,?,?,?,?)", out)
    return len(out)
