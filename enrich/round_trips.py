"""Round trips — out-and-back jobs from a depot, grouped from stitched journeys.

A round trip = consecutive journeys that leave a depot and return to a depot. The
farthest *named* place from the origin depot is the primary destination; named places
before/after it are the outbound / return via-points. Depots come from places.yaml
`depot:`/`home:` flags (fallback: the most-frequent journey origin). This is a derived
layer on top of `journeys` — journeys are never modified. Idempotent.

A trip that has left a depot but not yet returned is "open": no row is emitted (the
Overview shows it as "currently out"). Prints a small summary for STOP-1 review:
skipped leading journeys, the open trip, and any unlabeled farthest points demoted in
favour of a named destination (a places.yaml target list for the owner).
"""

import json
import math
import pathlib
from collections import Counter

import yaml

_ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
_RANK = {"long_haul": 3, "regional": 2, "local": 1, "yard": 0}
_DEST_TYPES = {"destination", "customer", "workshop"}  # eligible to be a primary destination


def _haversine_km(la0, lo0, la1, lo1):
    if None in (la0, lo0, la1, lo1):
        return 0.0
    r = 6371.0
    p0, p1 = math.radians(la0), math.radians(la1)
    dp, dl = math.radians(la1 - la0), math.radians(lo1 - lo0)
    a = math.sin(dp / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _depot_labels():
    path = _ROOT / "places.yaml"
    if not path.exists():
        return set()
    try:
        entries = yaml.safe_load(path.read_text()) or []
    except Exception:
        return set()
    return {e["label"] for e in entries
            if isinstance(e, dict) and e.get("label") and (e.get("depot") or e.get("home"))}


def rebuild(con, unit_id):
    con.execute("DELETE FROM round_trips")
    places = {int(r[0]): {"label": r[1], "lat": r[2], "lon": r[3], "named": r[4] == 0,
                          "type": r[5] or "destination"}
              for r in con.execute(
                  "SELECT place_id, label, lat, lon, needs_label, type FROM places")}
    depot_lbls = _depot_labels()
    depot_ids = {pid for pid, p in places.items() if p["label"] in depot_lbls}

    jrows = con.execute(
        "SELECT journey_id, start_ts, end_ts, origin_place_id, dest_place_id, distance_m, "
        "journey_character FROM journeys WHERE unit_id=? ORDER BY start_ts", (unit_id,)).fetchall()
    if not depot_ids:  # fallback: the most-frequent journey origin is "home"
        c = Counter(int(r[3]) for r in jrows if r[3] is not None)
        depot_ids = {c.most_common(1)[0][0]} if c else set()

    def is_depot(pid):
        return pid is not None and int(pid) in depot_ids

    out, demoted, skipped, open_trip = [], [], 0, None
    i, n = 0, len(jrows)
    while i < n:
        if not is_depot(jrows[i][3]):           # only start a round trip at a depot
            skipped += 1
            i += 1
            continue
        origin_depot = int(jrows[i][3])
        seg, closed = [], False
        while i < n:
            seg.append(jrows[i])
            dest = jrows[i][4]
            i += 1
            if is_depot(dest):
                closed = True
                break
        if not closed:                          # left a depot, never returned -> open
            open_trip = seg
            break

        odep = places.get(origin_depot, {})
        dests = [int(j[4]) for j in seg if j[4] is not None]
        far = max(dests, key=lambda p: _haversine_km(
            odep.get("lat"), odep.get("lon"),
            places.get(p, {}).get("lat"), places.get(p, {}).get("lon")), default=origin_depot)
        def _dist(p):
            return _haversine_km(odep.get("lat"), odep.get("lon"),
                                 places.get(p, {}).get("lat"), places.get(p, {}).get("lon"))

        named = [p for p in dests if places.get(p, {}).get("named") and p not in depot_ids]
        targets = [p for p in named if places.get(p, {}).get("type") in _DEST_TYPES]
        prim_cands = targets or named   # prefer real destinations; else any named; else farthest
        if prim_cands:
            prim = max(prim_cands, key=_dist)
            if far != prim and not places.get(far, {}).get("named"):
                fp = places.get(far, {})
                demoted.append((fp.get("label"), fp.get("lat"), fp.get("lon")))
        else:
            prim = far

        pidx = dests.index(prim) if prim in dests else len(dests) - 1

        def _vias(ids):
            return [places[p]["label"] for p in ids
                    if places.get(p, {}).get("named") and p not in depot_ids and p != prim]

        cls = max((j[6] for j in seg), key=lambda c: _RANK.get(c, 0))
        out.append((
            unit_id, int(seg[0][1]), int(seg[-1][2]), prim, places.get(prim, {}).get("label"),
            cls, round(sum((j[5] or 0) for j in seg) / 1000.0, 1),
            int(seg[-1][2]) - int(seg[0][1]),
            json.dumps([int(j[0]) for j in seg]), json.dumps(_vias(dests[:pidx])),
            json.dumps(_vias(dests[pidx + 1:]))))

    con.executemany(
        "INSERT INTO round_trips (unit_id, start_ts, end_ts, primary_destination_id, "
        "primary_destination_name, journey_class, total_distance_km, total_duration_s, "
        "constituent_journey_ids, via_places, return_via_places) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        out)

    if skipped:
        print(f"  round_trips: skipped {skipped} journey(s) not starting at a depot")
    if open_trip:
        last = places.get(int(open_trip[-1][4]), {}).get("label", "?") if open_trip[-1][4] else "?"
        from datetime import datetime, timezone
        since = datetime.fromtimestamp(int(open_trip[0][1]), timezone.utc).strftime("%Y-%m-%d")
        print(f"  round_trips: open trip — currently out at {last} since {since} (no row)")
    if demoted:
        print(f"  round_trips: unlabeled farthest points demoted: {len(demoted)} "
              f"(named destination used) -> {demoted}")
    return len(out)
