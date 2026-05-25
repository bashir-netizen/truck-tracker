"""Return-leg classification (Task 12 — EXPLORATORY, no UI yet).

For each completed *delivery* cycle, classify the leg AFTER the primary destination until the
next anchor:
  empty_return  deadhead — direct back, or only brief stops (cost without revenue)
  multi_drop    one load, several drops on the way back (each closer to home)
  backhaul      picked up + dropped new cargo on the way back (revenue both ways)
  ambiguous     doesn't fit cleanly / not enough signal
plus a confidence (high|medium|low). Writes return_leg_type / return_leg_confidence onto
delivery_cycles; prints a per-cycle report for owner validation. Reads delivery_cycles +
journeys + places only. Thin data (few completed deliveries) → expect mostly empty_return.
"""

import json

from enrich.round_trips import _haversine_km

DROP_MIN_S, DROP_MAX_S = 30 * 60, 2 * 3600       # an offload/drop
PICKUP_MIN_S, PICKUP_MAX_S = 1 * 3600, 4 * 3600  # a backhaul pickup at a non-loading place
EMPTY_TOTAL_S = 90 * 60                           # cumulative return dwell below this = empty


def _classify(stops):
    """stops: [(label, dwell_s, type, role, dist_home_km)] in return order -> (type, conf, notes)."""
    if not stops:
        return "empty_return", "high", "Direct return to the next anchor — no intermediate stops."
    total = sum(s[1] for s in stops)
    drops = [s for s in stops if DROP_MIN_S <= s[1] <= DROP_MAX_S and s[3] != "loading"]
    pickups = [s for s in stops if PICKUP_MIN_S <= s[1] <= PICKUP_MAX_S and s[3] != "loading"]
    if total < EMPTY_TOTAL_S:
        return ("empty_return", "medium",
                f"{len(stops)} brief stop(s), {total // 60} min total — no offload-length stay.")
    if pickups and DROP_MIN_S <= stops[-1][1] <= DROP_MAX_S:
        return ("backhaul", "low",
                f"Long stop at {pickups[0][0]} then a drop — possible pickup + delivery on the way back.")
    if len(drops) >= 2 and all(stops[i][4] >= stops[i + 1][4] for i in range(len(stops) - 1)):
        return "multi_drop", "medium", f"{len(drops)} drops, each closer to home — one load, several drops."
    return "ambiguous", "low", f"{len(stops)} stop(s), {total // 60} min — no clean empty/multi/backhaul fit."


def rebuild(con, unit_id):
    places = {int(r[0]): {"label": r[1], "lat": r[2], "lon": r[3], "type": r[4], "role": r[5]}
              for r in con.execute("SELECT place_id, label, lat, lon, type, suggested_role "
                                   "FROM places")}
    home = next((pid for pid, p in places.items() if p["type"] == "depot"), None)
    hp = places.get(home, {})

    def dist_home(pid):
        return _haversine_km(hp.get("lat"), hp.get("lon"),
                             places.get(pid, {}).get("lat"), places.get(pid, {}).get("lon"))

    cycles = con.execute(
        "SELECT cycle_id, destination_place_id, constituent_journey_ids, cycle_type "
        "FROM delivery_cycles WHERE unit_id=? ORDER BY cycle_start_ts", (unit_id,)).fetchall()
    report = []
    for cid, dest, cj, ctype in cycles:
        if ctype != "delivery" or dest is None:
            continue                                  # only delivery cycles have a return leg
        jids = json.loads(cj or "[]")
        if not jids:
            continue
        ph = ",".join("?" * len(jids))
        js = con.execute(f"SELECT start_ts, end_ts, dest_place_id FROM journeys "
                         f"WHERE journey_id IN ({ph}) ORDER BY start_ts", tuple(jids)).fetchall()
        di = max((i for i, j in enumerate(js) if j[2] is not None and int(j[2]) == int(dest)),
                 default=None)
        if di is None:
            continue
        ret = js[di + 1:]                             # journeys after leaving the destination
        stops = []
        for k, j in enumerate(ret[:-1]):              # last return journey arrives at the anchor
            d = j[2]
            if d is None:
                continue
            dwell = int(ret[k + 1][0]) - int(j[1])    # gap to the next return journey's start
            pl = places.get(int(d), {})
            stops.append((pl.get("label", "?"), dwell, pl.get("type"), pl.get("role"),
                          dist_home(int(d))))
        rtype, conf, notes = _classify(stops)
        con.execute("UPDATE delivery_cycles SET return_leg_type=?, return_leg_confidence=? "
                    "WHERE cycle_id=?", (rtype, conf, cid))
        report.append((cid, places.get(int(dest), {}).get("label", "?"),
                       [s[0] for s in stops], rtype, conf, notes))
    _print_report(report)
    return len(report)


def _print_report(report):
    print("  return-leg classification (Task 12, exploratory — owner to validate):")
    if not report:
        print("    (no completed delivery cycles to classify)")
        return
    summary = {}
    for cid, dest, path, rtype, conf, notes in report:
        summary[rtype] = summary.get(rtype, 0) + 1
        pth = " → ".join(path) if path else "(direct)"
        print(f"    cycle #{cid} ({dest}): return [{pth}] -> {rtype} ({conf})")
        print(f"        {notes}")
    print("    summary: " + ", ".join(f"{v} {k}" for k, v in sorted(summary.items())))
