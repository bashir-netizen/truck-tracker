"""Rolling driver score per ISO week, on Wialon's 0-10 eco scale.

For each week we sum eco-driving penalty points (config.PENALTY_POINTS),
normalise per 100 km driven, and convert to a 0-10 rank using Wialon's
documented penalty->rank table (higher = better). Distance comes from trips.

Wialon "Eco driving" rank conversion (penalty points -> rank), from the
Wialon Hosting help, "Eco driving" report table:
    0 pts -> 10.0,  17 -> 9,  38 -> 8,  67 -> 7,  107 -> 6,
    167 -> 5,  267 -> 4,  467 -> 3,  1067 -> 2,  > -> toward 1
We interpolate linearly within each band. Source:
https://help.wialon.com/en/wialon-hosting/user-guide/monitoring-system/reports/report-templates/report-contents/tables/table-types/eco-driving
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import config

# (penalty_lo, penalty_hi, rank_at_lo, rank_at_hi) — Wialon's documented bands.
_RANK_BANDS = [
    (0, 17, 10.0, 9.0), (17, 38, 9.0, 8.0), (38, 67, 8.0, 7.0),
    (67, 107, 7.0, 6.0), (107, 167, 6.0, 5.0), (167, 267, 5.0, 4.0),
    (267, 467, 4.0, 3.0), (467, 1067, 3.0, 2.0),
]


def penalties_to_rank(p):
    """Map summed penalty points to Wialon's 0-10 rank (linear within bands)."""
    if p <= 0:
        return 10.0
    for lo, hi, r_lo, r_hi in _RANK_BANDS:
        if p <= hi:
            return round(r_lo + (p - lo) / (hi - lo) * (r_hi - r_lo), 1)
    return round(max(1.0, 2.0 - (p - 1067) / 1067.0), 1)  # beyond the table


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
        penalty = sum(config.PENALTY_POINTS.get(t, 10) * n for t, n in c.items())
        km = distance_km[w]
        per_100km = penalty / (km / 100.0) if km > 0 else penalty
        score = penalties_to_rank(per_100km)
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
