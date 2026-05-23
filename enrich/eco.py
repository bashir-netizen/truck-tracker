"""Per-event eco flags (derived) — hard-safety classification for the Driver page.

Reads raw eco_events, writes the derived eco_flags table; never modifies raw.
A "hard-safety" event is objectively unsafe regardless of Kenyan road conditions
(which constantly trigger mild/medium accel/brake/turn events):
  - any extreme-severity event (any type).

Deferred (not evaluated): speeding ≥20 km/h over the limit for ≥60 s, and ≥30 km/h
over (any duration). These need km/h-over-limit and per-event duration, which this
unit's eco report does not expose (we only get absolute max speed; duration is
blank). They are documented in docs/scoring.md and add nothing for this driver
(no medium/extreme speeding). Night highway driving is NOT hard-safety — it's
normal scheduled long-haul on Kenyan roads; see the Night-driving panel instead.
"""

import json

import config  # noqa: F401  (kept for thresholds referenced by docs/future clauses)


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


def hard_safety(severity):
    """1 if the event is objectively unsafe regardless of road conditions."""
    return 1 if severity == "extreme" else 0


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
        rows.append((unit_id, ts, etype, sev, character_at(ts), hard_safety(sev)))

    con.executemany(
        "INSERT OR IGNORE INTO eco_flags "
        "(unit_id, ts, type, severity, journey_character, hard_safety) "
        "VALUES (?,?,?,?,?,?)", rows)
    return len(rows)
