"""Rolling driver score per ISO week, on Wialon's 0-10 eco scale.

For each week we sum the eco-driving penalty points (config.PENALTY_POINTS, the
unit's exact configured penalties) and convert that TOTAL to a 0-10 rank via
Wialon's documented penalty->rank table (higher = better). We deliberately do
NOT normalise per distance, so the result reproduces Wialon's own number.

Computed using Wialon's documented penalty→rank formula with this unit's configured
penalty points. Cross-checkable against Wialon's Eco Driving tab. The remote report
API does not expose this value, so we reproduce it locally — verified live 2026-05-23
(the `unit_ecodriving` report returns only violation rows; requested rank/rating/
penalties columns are dropped, stats/total empty). This unit: computed 1.0 vs Wialon's
~1.1. It reads structurally low on Kenyan roads (reference only).

Wialon "Eco driving" rank conversion (penalty points -> rank), from the
Wialon Hosting help, "Eco driving" report table:
    0 pts -> 10.0,  17 -> 9,  38 -> 8,  67 -> 7,  107 -> 6,
    167 -> 5,  267 -> 4,  467 -> 3,  1067 -> 2,  > -> toward 1
We interpolate linearly within each band. Source:
https://help.wialon.com/en/wialon-hosting/user-guide/monitoring-system/reports/report-templates/report-contents/tables/table-types/eco-driving
"""

import json
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


def _penalty_key(violation_name):
    """'Acceleration: medium' -> 'acceleration_medium' (matches PENALTY_POINTS)."""
    parts = [p.strip().lower() for p in (violation_name or "").split(":")]
    crit = parts[0].split()[-1] if parts and parts[0] else ""
    sev = parts[1] if len(parts) > 1 else "medium"
    return f"{crit}_{sev}"


def event_penalty(raw):
    """Penalty points for one eco event, from its violation_name in `raw`."""
    try:
        cell = json.loads(raw)["c"][4]
        vn = cell.get("t") if isinstance(cell, dict) else cell
    except Exception:
        vn = None
    return config.PENALTY_POINTS.get(_penalty_key(vn), config.PENALTY_DEFAULT)


def week_start(ts):
    """Epoch of the Monday 00:00 UTC for the week containing ts."""
    dt = datetime.fromtimestamp(ts, timezone.utc)
    monday = (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return int(monday.timestamp())


def rebuild(con, unit_id):
    con.execute("DELETE FROM driver_score")

    counts = defaultdict(lambda: defaultdict(int))  # week -> type -> n
    penalty_pts = defaultdict(float)                 # week -> summed penalty points
    distance_km = defaultdict(float)                 # week -> km
    weeks = set()

    for ts, etype, raw in con.execute(
            "SELECT ts, type, raw FROM eco_events WHERE unit_id=?", (unit_id,)):
        w = week_start(ts)
        counts[w][etype] += 1
        penalty_pts[w] += event_penalty(raw)
        weeks.add(w)

    for sts, dist in con.execute(
            "SELECT start_ts, distance_m FROM trips WHERE unit_id=?", (unit_id,)):
        w = week_start(sts)
        distance_km[w] += (dist or 0) / 1000.0
        weeks.add(w)

    hard = defaultdict(int)  # week -> hard-safety event count
    for ts, hs in con.execute(
            "SELECT ts, hard_safety FROM eco_flags WHERE unit_id=?", (unit_id,)):
        if hs:
            w = week_start(ts)
            hard[w] += 1
            weeks.add(w)

    out = []
    for w in sorted(weeks):
        c = counts[w]
        # Total penalty -> Wialon rank, NOT distance-normalised, so it reproduces
        # Wialon's own report (reference only; reads structurally low on Kenyan roads).
        score = penalties_to_rank(penalty_pts[w])
        out.append((
            unit_id, w, w + 7 * 86400, round(score, 1), int(round(distance_km[w] * 1000)),
            c.get("harsh_accel", 0), c.get("harsh_brake", 0),
            c.get("harsh_corner", 0), c.get("speeding", 0), hard[w],
        ))

    con.executemany(
        "INSERT INTO driver_score "
        "(unit_id, period_start, period_end, score, distance_m, accel_count, "
        " brake_count, corner_count, speeding_count, hard_safety_count) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", out)
    return len(out)
