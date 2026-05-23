"""Per-event eco flags (derived) — hard-safety classification for the Driver page.

Reads raw eco_events, writes the derived eco_flags table; never modifies raw.
A "hard-safety" event is one that signals genuine risk regardless of Kenyan road
conditions (which constantly trigger mild/medium accel/brake/turn events):
  - any extreme-severity event, OR
  - speeding at medium/extreme severity, OR
  - a night event (19:00-05:00 local) on a long-haul/regional journey.
"""

import json
from datetime import datetime, timezone

import config


def severity_of(raw):
    """Extract severity ('mild'/'medium'/'extreme') from an event's violation_name."""
    try:
        cell = json.loads(raw)["c"][4]
        vn = cell.get("t") if isinstance(cell, dict) else cell
    except Exception:
        vn = None
    if not vn:
        return None
    parts = [p.strip().lower() for p in str(vn).split(":")]
    return parts[1] if len(parts) > 1 else None


def is_night(ts):
    """True if the event's local (Kenya) hour is in the night window."""
    hour = datetime.fromtimestamp(ts + config.KENYA_UTC_OFFSET_H * 3600, timezone.utc).hour
    return hour >= config.NIGHT_START_HOUR or hour < config.NIGHT_END_HOUR


def hard_safety(etype, severity, journey_character, ts):
    if severity == "extreme":
        return 1
    if etype == "speeding" and severity in config.HARD_SAFETY_SPEEDING_SEVERITIES:
        return 1
    if is_night(ts) and journey_character in ("long_haul", "regional"):
        return 1
    return 0


def rebuild(con, unit_id):
    con.execute("DELETE FROM eco_flags")
    journeys = con.execute(
        "SELECT start_ts, end_ts, journey_character FROM journeys WHERE unit_id=?",
        (unit_id,)).fetchall()

    def character_at(ts):
        for s, e, ch in journeys:
            if s <= ts <= (e or s):
                return ch
        return None

    rows = []
    for ts, etype, raw in con.execute(
            "SELECT ts, type, raw FROM eco_events WHERE unit_id=?", (unit_id,)):
        sev = severity_of(raw)
        ch = character_at(ts)
        rows.append((unit_id, ts, etype, sev, ch, hard_safety(etype, sev, ch, ts)))

    con.executemany(
        "INSERT OR IGNORE INTO eco_flags "
        "(unit_id, ts, type, severity, journey_character, hard_safety) "
        "VALUES (?,?,?,?,?,?)", rows)
    return len(rows)
