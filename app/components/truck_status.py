"""Current truck status — period-independent "where is the truck right now".

Keeps distinct the three units the Overview must not conflate:
  - journey leg : one movement segment between stops (a `journeys` row)
  - round trip  : a completed depot -> away -> depot cycle (a `round_trips` row)
  - open trip   : currently away from a depot, not yet a completed round trip

`compute()` answers "is it home or out, where, and how worried should I be" —
read-only from the latest journeys, NOT the selected dashboard period. The "now"
reference is the last data we hold (`db.last_data_ts`), per the "as of last
ingestion" freshness contract; wall-clock is used only to flag a silent device.
"""

import time

from app.components import db, theme

_DAY = 86400
WARN_AWAY_S = 7 * _DAY        # away longer than this -> warn
CRIT_AWAY_S = 14 * _DAY       # away longer than this -> critical
SILENT_S = 24 * 3600         # no data newer than this -> device silent (critical)

# Escalation colour. NB theme.ACCENT == STATUS_CRITICAL (Kenyan red), so the UI also
# escalates by treatment (⚠ marker, tinted callout), not hue alone.
LEVEL_COLOR = {"attention": theme.ACCENT, "warn": theme.STATUS_WARN,
               "critical": theme.STATUS_CRITICAL}


def compute():
    """Period-independent current status dict. See the module docstring for the units.

    Keys: away (bool), place, place_id, place_unlabeled, away_since, arrived_ts,
    away_s, silent, last_home_ts, last_data_ts, since_seen_s,
    level ('home'|'attention'|'warn'|'critical').
    """
    last_data = db.last_data_ts() or int(time.time())
    silent = (time.time() - last_data) > SILENT_S
    status = {"away": False, "place": None, "place_id": None, "place_unlabeled": False,
              "away_since": None, "arrived_ts": None, "away_s": 0, "silent": silent,
              "last_home_ts": None, "level": "home", "last_data_ts": last_data,
              "since_seen_s": max(0, int(time.time()) - last_data)}

    depot_ids = {int(r.place_id) for r in
                 db.q("SELECT place_id FROM places WHERE type='depot'").itertuples()}
    if not depot_ids:
        return status

    ph = ",".join("?" * len(depot_ids))
    last_home = db.scalar(f"SELECT MAX(end_ts) FROM journeys WHERE dest_place_id IN ({ph})",
                          tuple(depot_ids))
    if last_home is None:            # never seen at a depot -> can't judge; treat as home
        return status
    status["last_home_ts"] = int(last_home)

    after = db.q("SELECT start_ts, end_ts, dest_place_id FROM journeys WHERE start_ts > ? "
                 "ORDER BY start_ts", (status["last_home_ts"],))
    if after.empty:
        return status                # at home since last_home_ts

    # legs since the last home arrival = the open trip; current place = last known off-depot dest
    known = [r for r in after.itertuples()
             if r.dest_place_id == r.dest_place_id and int(r.dest_place_id) not in depot_ids]
    away_since = int(after.iloc[0]["start_ts"])
    if known:
        last_leg = known[-1]
        pid = int(last_leg.dest_place_id)
        prow = db.q("SELECT label, needs_label FROM places WHERE place_id=?", (pid,))
        place = prow.iloc[0]["label"] if not prow.empty else "an unknown place"
        unlabeled = (not prow.empty and int(prow.iloc[0]["needs_label"]) == 1)
        arrived = int(last_leg.end_ts)
    else:                            # out, but the current spot isn't a known place yet
        pid, place, unlabeled, arrived = None, "an unknown place", True, int(after.iloc[-1]["end_ts"])

    status.update(away=True, place_id=pid, place=place, place_unlabeled=unlabeled,
                  away_since=away_since, arrived_ts=arrived, away_s=max(0, last_data - away_since))

    if status["away_s"] > CRIT_AWAY_S or silent:
        status["level"] = "critical"
    elif status["away_s"] > WARN_AWAY_S or unlabeled:
        status["level"] = "warn"
    else:
        status["level"] = "attention"
    return status
