"""Detect anomalies and rebuild the `anomalies` table.

Four checks, all thresholds from config:
  - unusual_fill     : a fill larger than the tank, or a post-fill level
                       above tank capacity (sensor/calibration or abuse).
  - fuel_drop        : between two fills, the level fell more than the
                       engine could have burned — a possible siphon/theft.
  - consumption_drift: a trip's L/100km well above the fleet baseline.
  - device_silent    : no fresh data for longer than the threshold.

This is a single cohesive module (not in the original layout sketch)
because the anomalies table and the Anomalies dashboard page need one
place that owns detection, with every threshold living in config.
"""

import time

import config

CAPACITY = config.TANK_CAPACITY_L


def _detect_unusual_fills(con, unit_id):
    found = []
    for ts, vol, after in con.execute(
            "SELECT ts, volume_l, level_after_l FROM fillings WHERE unit_id=?", (unit_id,)):
        if vol is not None and vol > CAPACITY:
            found.append((ts, "unusual_fill", "high",
                          f"Fill of {vol:.0f} L exceeds tank capacity ({CAPACITY} L)"))
        elif after is not None and after > CAPACITY * 1.05:
            found.append((ts, "unusual_fill", "medium",
                          f"Post-fill level {after:.0f} L above tank capacity"))
    return found


def _detect_fuel_drops(con, unit_id):
    """Level dropped between fills beyond what trips consumed in between."""
    fills = con.execute(
        "SELECT ts, level_before_l, level_after_l FROM fillings "
        "WHERE unit_id=? ORDER BY ts", (unit_id,)).fetchall()
    threshold = config.FUEL_DROP_PCT / 100.0 * CAPACITY
    found = []
    for (prev_ts, _, prev_after), (ts, before, _) in zip(fills, fills[1:]):
        if prev_after is None or before is None:
            continue
        consumed = con.execute(
            "SELECT COALESCE(SUM(consumed_l), 0) FROM trips "
            "WHERE unit_id=? AND start_ts>? AND start_ts<=?",
            (unit_id, prev_ts, ts)).fetchone()[0]
        missing = (prev_after - consumed) - before
        if missing > threshold:
            found.append((ts, "fuel_drop", "high",
                          f"{missing:.0f} L unaccounted between fills "
                          f"(expected {prev_after - consumed:.0f} L, saw {before:.0f} L)"))
    return found


def _detect_consumption_drift(con, unit_id):
    """Weekly economy vs the pooled baseline (robust to per-trip noise)."""
    from collections import defaultdict
    from enrich.driver import week_start

    week_km, week_l = defaultdict(float), defaultdict(float)
    total_km = total_l = 0.0
    for ts, dist, consumed in con.execute(
            "SELECT start_ts, distance_m, consumed_l FROM trips "
            "WHERE unit_id=? AND consumed_l>0 AND distance_m>0", (unit_id,)):
        km = dist / 1000.0
        if km < config.DRIFT_MIN_TRIP_KM:
            continue
        w = week_start(ts)
        week_km[w] += km
        week_l[w] += consumed
        total_km += km
        total_l += consumed

    if total_km <= 0:
        return []
    baseline = total_l / total_km * 100
    limit = baseline * (1 + config.CONSUMPTION_DRIFT_PCT / 100.0)
    found = []
    for w in sorted(week_km):
        if week_km[w] < config.DRIFT_MIN_WEEK_KM:
            continue  # too little driving that week to judge
        rate = week_l[w] / week_km[w] * 100
        if rate > limit:
            found.append((w, "consumption_drift", "medium",
                          f"Week economy {rate:.1f} L/100km vs {baseline:.1f} baseline"))
    return found


def _detect_device_silent(con, unit_id, now):
    last = con.execute(
        "SELECT MAX(ts) FROM unit_state WHERE unit_id=?", (unit_id,)).fetchone()[0]
    if last and (now - last) > config.DEVICE_SILENT_HOURS * 3600:
        hours = (now - last) // 3600
        return [(last, "device_silent", "high", f"No new data for {hours} h")]
    return []


def rebuild(con, unit_id, now=None):
    now = now or int(time.time())
    con.execute("DELETE FROM anomalies")
    rows = (_detect_unusual_fills(con, unit_id)
            + _detect_fuel_drops(con, unit_id)
            + _detect_consumption_drift(con, unit_id)
            + _detect_device_silent(con, unit_id, now))
    con.executemany(
        "INSERT OR REPLACE INTO anomalies (unit_id, ts, type, severity, detail) "
        "VALUES (?,?,?,?,?)",
        [(unit_id, ts, typ, sev, detail) for ts, typ, sev, detail in rows])
    return len(rows)
